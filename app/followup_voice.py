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

from app import redis_store
import os
import re
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
# 0.25s. This was 0.8s and then 2.5s while the phone played these as separate
# FILES, where every boundary was an audible gap and bigger pieces meant fewer
# of them. The follow-up now plays raw PCM through one continuous queue source,
# so a boundary costs nothing and the only thing size controls is how soon the
# first sound arrives.
#
# Not smaller than this: each piece is a base64 SSE frame and a buffer
# conversion on the phone, and past a few frames a second that work starts to
# matter more than the latency it saves.
FLUSH_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS * 0.25)


# Which account-wide lease each open socket holds, so closing it — from any
# of the several places sockets close — hands the slot back.
_socket_leases: Dict[int, str] = {}


async def _close_socket(ws) -> None:
    lease = _socket_leases.pop(id(ws), None)
    try:
        await ws.close()
    except Exception:
        pass
    await redis_store.rumik_gate_release(lease)


async def _open_socket():
    """A fresh Rumik socket, minted, connected, and counted.

    Counted against the same account-wide gate as the classroom pool: these
    sockets talk to the same Rumik account, and a follow-up rush that is
    invisible to the pool eats the classes' headroom all the same.
    """
    import websockets
    import requests

    key = os.getenv("RUMIK_API_KEY")
    if not key:
        raise RuntimeError("RUMIK_API_KEY is not set")

    gate = await redis_store.rumik_gate_acquire(timeout_s=3.0)
    if gate is None:
        raise RuntimeError("Rumik account-wide connection slots are exhausted")

    def _mint():
        return requests.post(
            f"{RUMIK_TTS_ENDPOINT}/v1/tts/ws-connect",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"model": RUMIK_MODEL, "text": "Init"},
            timeout=8,
        ).json()

    try:
        loop = asyncio.get_event_loop()
        handshake = await loop.run_in_executor(None, _mint)
        ws_url, token = handshake.get("ws_url"), handshake.get("token")
        if not ws_url or not token:
            raise RuntimeError("Rumik would not hand out a socket")
        ws = await websockets.connect(f"{ws_url}?token={token}",
                                      ping_interval=None, close_timeout=5.0)
    except Exception:
        await redis_store.rumik_gate_release(gate)
        raise
    _socket_leases[id(ws)] = gate
    return ws


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
# TWO warm sockets, because the answer now needs two at once: speak_chunks
# synthesises one sentence ahead, so sentence 1 takes a socket and sentence 2
# starts on another in the same breath. With a single-slot warm pool the
# second was always cold, hiding a ~1.7s handshake inside sentence 2's
# synthesis time — the exact cost prewarming exists to remove.
_WARM_DEPTH = 2
_warm: List[Tuple[Any, float]] = []
_warming: List[asyncio.Task] = []


def prewarm(tutor_voice: Optional[str] = None,
            language: Optional[str] = None) -> None:
    """Open sockets in the background until the pool holds `_WARM_DEPTH`.

    Fire and forget: a socket that fails to open costs nothing, because
    `_take_socket` falls back to opening one the usual way.
    """
    _warming[:] = [t for t in _warming if not t.done()]
    want = _WARM_DEPTH - len(_warm) - len(_warming)
    if want <= 0:
        return

    async def _fill():
        try:
            ws = await _open_socket()
            entry = (ws, time.time())
            _warm.append(entry)
            logger.info("[FOLLOWUP TTS] socket warmed ahead of the answer "
                        "(%d ready)", len(_warm))

            async def _reap():
                # An idle warm socket now holds an ACCOUNT-WIDE slot (the
                # global gate counts every open connection), and nothing used
                # to close one that was never taken — with 4 workers warming
                # 2 each, up to 8 of the 50 slots could sit parked in dead
                # sockets Rumik had long since dropped. Past its TTL it is
                # unusable anyway; close it and hand the slot back.
                await asyncio.sleep(_WARM_TTL_S + 5)
                if entry in _warm:
                    _warm.remove(entry)
                    await _close_socket(entry[0])
                    logger.info("[FOLLOWUP TTS] idle warm socket reaped — "
                                "account slot freed")

            asyncio.get_event_loop().create_task(_reap())
        except Exception as err:
            logger.info("[FOLLOWUP TTS] could not warm a socket (%s) — the "
                        "next synthesis opens its own", err)

    try:
        loop = asyncio.get_event_loop()
        for _ in range(want):
            _warming.append(loop.create_task(_fill()))
    except RuntimeError:
        # No running loop (a sync caller). Warming is an optimisation, and
        # skipping it only costs the handshake it was meant to save.
        pass


async def _take_socket():
    """A warmed socket if one is waiting and still fresh, else a new one."""
    while _warm:
        ws, opened = _warm.pop(0)
        if time.time() - opened < _WARM_TTL_S and not getattr(ws, "closed", False):
            return ws
        # Past its welcome: Rumik drops an idle socket, and finding that out by
        # sending a sentence down it costs more than opening a new one.
        await _close_socket(ws)
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
        await _close_socket(ws)


async def _synthesize(text: str, voice_preset: str) -> bytes:
    # The warmed socket, same as the streaming path: the handshake is 1.76s of
    # the wait and it does not have to be paid after the answer exists.
    ws = await _take_socket()
    try:
        sent_at = time.time()
        first_frame_ms: Optional[int] = None
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
                if first_frame_ms is None and msg:
                    first_frame_ms = int((time.time() - sent_at) * 1000)
                buf.extend(msg)
            elif isinstance(msg, str):
                payload = json.loads(msg)
                if payload.get("type") in ("done", "complete", "finish", "end"):
                    break
                if payload.get("error") or payload.get("code") == "RATE_LIMITED":
                    logger.warning("[FOLLOWUP TTS] refused: %s",
                                   payload.get("message") or payload.get("code"))
                    break
        # The number that settles "is Rumik slow, or are we?": its first frame
        # against its last. A fast first frame and a slow finish means the
        # wait is OUR whole-clip collection — a streaming player's gain, per
        # sentence, is exactly the difference between these two.
        if buf:
            logger.info(
                "[FOLLOWUP TTS] first frame at %sms, complete at %dms (%d chars)",
                first_frame_ms if first_frame_ms is not None else "?",
                int((time.time() - sent_at) * 1000), len(text),
            )
        return bytes(buf)
    finally:
        await _close_socket(ws)


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


# The FIRST clip is the whole wait before the student hears anything, and
# Rumik synthesizes at roughly half realtime — a 69-char opener became 7.2s
# of audio and took 3.9s to make, all of it silence. A first sentence over
# this is split at its last clause break (comma, dash, semicolon) inside the
# limit: a clause break is where a speaker pauses anyway, so the join lands
# on a breath that was already there. No clause break, no split — a mid-word
# cut is worse than the wait.
FIRST_CLIP_MAX_CHARS = 70

_CLAUSE_BREAK = re.compile(r'[,;:—–]\s+|\s+—\s+')


def _split_first_clip(sentence: str) -> list:
    """[short opener, remainder] at a clause break, or [sentence] whole."""
    if len(sentence) <= FIRST_CLIP_MAX_CHARS:
        return [sentence]
    breaks = [m.end() for m in _CLAUSE_BREAK.finditer(sentence)]
    inside = [b for b in breaks if 15 <= b <= FIRST_CLIP_MAX_CHARS]
    if inside:
        cut = inside[-1]
    else:
        # No break inside the window. The FIRST break beyond it still beats
        # no split at all — a 90-char opener is half the silence of a
        # 144-char one — as long as it leaves a real remainder.
        beyond = [b for b in breaks if b >= 15 and len(sentence) - b >= 15]
        if not beyond:
            return [sentence]
        cut = beyond[0]
    return [sentence[:cut].rstrip(), sentence[cut:].strip()]


# The most the voice will say, whatever the model wrote.
#
# The prompt asks for ~200 characters; this is the backstop for when it does
# not comply, because a prompt is a request and this is the thing the student
# actually waits through. 320 sits well above an ordinary two or three sentence
# answer, so it never trims one of those — it only catches a runaway.
#
# Trimmed at a SENTENCE boundary, never mid-thought — and never the CLOSE.
# The prompt ends every real answer with a short check-and-invite question as
# its final sentence, and trailing-first trimming deleted exactly that: a
# 343-char reply lost its "did you get that?" and kept its facts, which is
# the textbook ending the close exists to prevent. When the final sentence is
# a short question it is preserved and the cut moves forward; what gets
# dropped is explanation, which is on the board being read anyway.
MAX_SPOKEN_CHARS = 360

# A closing question longer than this is not a close, it is more explanation
# with a question mark on it — trimmed like anything else.
MAX_CLOSE_CHARS = 60


def cap_spoken(text: str) -> str:
    """`text` trimmed to whole sentences within `MAX_SPOKEN_CHARS`.

    The first sentence is always kept even when it alone is over the cap —
    `_spoken_sentences` will split it for Rumik, and a long opener is worth
    hearing where an empty answer is not.
    """
    said = (text or "").strip()
    if len(said) <= MAX_SPOKEN_CHARS:
        return said

    from app.drona.voice_proxy import split_into_sentences

    sentences = [x.strip() for x in (split_into_sentences(said, min_chars=0)
                                     or [said]) if x.strip()]
    # The teacher's close, if the reply ends on one. Set aside FIRST, so the
    # budget below is spent on explanation and the handover survives the cut.
    close = None
    if (len(sentences) > 1 and sentences[-1].endswith("?")
            and len(sentences[-1]) <= MAX_CLOSE_CHARS):
        close = sentences.pop()

    budget = MAX_SPOKEN_CHARS - (len(close) + 1 if close else 0)
    kept: list = []
    for sentence in sentences:
        candidate = f"{' '.join(kept)} {sentence}".strip() if kept else sentence
        if kept and len(candidate) > budget:
            break
        kept.append(sentence)
    out = " ".join(kept).strip()
    if close:
        out = f"{out} {close}".strip() if out else close
    out = out or said
    if len(out) < len(said):
        logger.info("[FOLLOWUP TTS] spoken trimmed %d -> %d chars at a sentence "
                    "boundary (cap %d%s)", len(said), len(out), MAX_SPOKEN_CHARS,
                    ", close preserved" if close else "")
    return out


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
        if not out:
            # Only the first sentence: everything after it is synthesized
            # while something else is already playing, so its length costs
            # nothing the student can hear.
            pieces = _split_first_clip(sentence)
            if len(pieces) == 2:
                out.append(pieces[0])
                sentence = pieces[1]
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
# No cached opener. One was built and removed, and the reasons are worth
# keeping because they are about Rumik rather than about the code.
#
# It worked, in the narrow sense: first sound went from ~2.9s to 0.29s. It
# sounded wrong anyway. A cached line cannot know what was asked, so it is
# generic by construction, and a generic line in front of a specific answer
# reads as a stall rather than as a teacher thinking. On top of that Rumik
# paces identical text differently between calls — the same sentence measured
# 0.061 and 0.103 seconds per character on two runs — so a cached clip's
# delivery never quite matches the live sentence behind it. Auditioning each
# take (synthesise, measure, re-take if dragged) fixed the dragging and did
# nothing for the mismatch.
#
# So the answer starts when its first sentence is ready. Measured over six
# runs on a warm socket: 1.89, 1.98, 2.09, 2.82, 2.83, 3.82 seconds — median
# 2.46s, and most of it is Rumik's own first-byte time, which is not ours to
# shorten.


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
    del language  # only the cached opener used it, and that was removed
    said = cap_spoken(text)
    if not said:
        return
    preset = preset_for(tutor_voice)
    sentences = _spoken_sentences(said)
    started = time.time()

    # ONE sentence ahead, always. Serially, sentence n+1's synthesis began
    # only when n's finished — so the student heard a 1-2s hole between
    # sentences whenever the next needed longer to make than the current
    # took to play, which at Rumik's roughly half-realtime pace is most of
    # the time. And the phone plays clips at 1.15x, ending each one 13%
    # sooner than its nominal length: the speed-up bought pace and paid for
    # it in exactly this gap. One ahead rather than all at once: every
    # in-flight synthesis holds a Rumik socket, and the classroom pool
    # competes for the same supply.
    def begin(i: int) -> asyncio.Task:
        return asyncio.create_task(_synthesize(sentences[i], preset))

    pending = begin(0)
    try:
        for idx, sentence in enumerate(sentences, 1):
            current = pending
            pending = begin(idx) if idx < len(sentences) else None
            try:
                pcm = await current
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
    finally:
        # A student who pressed Done mid-answer cancels this generator; the
        # sentence being made ahead must not keep a socket warm for nobody.
        if pending is not None and not pending.done():
            pending.cancel()


def _flush_sizes(flushed: int) -> tuple:
    """Bytes the next PCM flush waits for: a 0.25s, 0.5s, 1s ladder."""
    return (12000,) if flushed == 0 else (24000,) if flushed == 1 else (48000,)


async def speak_pcm(text: str, tutor_voice: Optional[str] = None):
    """Raw PCM in flushes, yielded as Rumik produces it — nothing waits for a
    clip to finish existing before it can start playing.

    The whole-sentence path (`speak_chunks`) holds every clip until its last
    frame because the phone plays FILES; measured, that wait is seconds per
    sentence at Rumik's roughly half-realtime pace. This path hands back
    ~0.25s of audio the moment the first frames arrive and ~1s pieces after,
    for a phone that schedules PCM buffers directly.

    Yields bare Int16LE/24kHz/mono bytes. The first flush is deliberately
    small — the first sound is the one the student is waiting for.
    """
    said = cap_spoken(text)
    if not said:
        return
    preset = preset_for(tutor_voice)
    sentences = _spoken_sentences(said)
    started = time.time()
    first_flush = True
    flushed = 0
    for idx, sentence in enumerate(sentences, 1):
        buf = bytearray()
        got = 0
        async for piece in _synthesize_stream(sentence, preset):
            buf.extend(piece)
            got += len(piece)
            # A ladder, not a cliff: 0.25s, 0.5s, then 1s pieces. Jumping
            # from a quarter-second first flush straight to one-second
            # pieces drained the player at the start — the shaky first word.
            while len(buf) >= _flush_sizes(flushed)[0]:
                take = _flush_sizes(flushed)[0]
                out = bytes(buf[:take])
                del buf[:take]
                if first_flush:
                    logger.info("[FOLLOWUP TTS] first pcm flush at t+%dms",
                                int((time.time() - started) * 1000))
                    first_flush = False
                flushed += 1
                yield out
        if len(buf) % 2:
            # Int16 frames are even; a torn trailing byte is noise, not audio.
            del buf[-1:]
        if buf:
            yield bytes(buf)
        logger.info("[FOLLOWUP TTS] %s sentence %d/%d streamed %d bytes at t+%dms",
                    preset, idx, len(sentences), got,
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
    said = cap_spoken(text)
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
