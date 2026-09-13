"""The follow-up answer stream carries its own voice.

The phone used to receive `spoken` and then make a SECOND request to have it
read — a round trip and a request setup spent in silence after the words were
already known. Now synthesis happens server-side into the same SSE stream as
the steps. These tests pin the contract the phone relies on:

  - `spoken` is marked inline, so the phone knows not to fetch the voice back
  - audio frames arrive in this stream, after `spoken`
  - `answered` fires when the ANSWER is done, so the screen can settle its
    surface while audio is still synthesising
  - `voice_done` reports chunks, zero meaning "fall back to /speak-stream"
  - `done` is last, after both the answer and the voice
"""

import asyncio
import json

import app.routers.doubts as doubts


def _frames(response):
    """[(event, payload)] out of the SSE body, in arrival order."""

    async def read():
        out = []
        async for block in response.body_iterator:
            for frame in block.split("\n\n"):
                if not frame.strip():
                    continue
                name, data = None, None
                for line in frame.split("\n"):
                    if line.startswith("event: "):
                        name = line[len("event: "):]
                    elif line.startswith("data: "):
                        data = json.loads(line[len("data: "):])
                out.append((name, data))
        return out

    return asyncio.run(read())


def _fake_llm(*_args, **_kwargs):
    yield "spoken", {"text": "Because the current splits by resistance."}
    yield "step", {"n": 1, "text": "$I = V/R$"}
    yield "step", {"n": 2, "text": "$I_4 = 2/5$"}


def test_inline_voice_rides_the_answer_stream(monkeypatch):
    async def fake_speak(text, voice=None, language=None):
        assert "current splits" in text
        assert voice == "drona"
        for i in (1, 2):
            # Real synthesis takes seconds; this pause is only so the answer
            # finishes first and the stream is PROVEN to stay open for audio.
            await asyncio.sleep(0.02)
            yield i, 2, b"RIFFfakewav"

    monkeypatch.setattr(doubts, "stream_followup", _fake_llm)
    monkeypatch.setattr(doubts.followup_voice, "speak_chunks", fake_speak)
    monkeypatch.setattr(doubts.followup_voice, "prewarm", lambda *a, **k: None)
    monkeypatch.setattr(doubts, "_tutor_voice_for", lambda user_id: "drona")

    frames = _frames(doubts._followup_response(
        {"id": "d1"}, "d1", "u1", "why does it split?", []))
    names = [n for n, _ in frames]

    assert names.count("spoken") == 1
    spoken = dict(frames)["spoken"]
    assert spoken["voice"] == "inline"

    assert names.count("audio") == 2
    assert names.index("spoken") < names.index("audio")
    audio = [p for n, p in frames if n == "audio"]
    assert audio[0]["n"] == 1 and audio[0]["total"] == 2 and audio[0]["b64"]

    # The answer settles the screen; the voice must not gate it.
    assert "answered" in names
    assert names.index("answered") > max(i for i, n in enumerate(names) if n == "step")

    assert dict(frames)["voice_done"]["chunks"] == 2
    assert names[-1] == "done"


def test_a_voice_that_fails_still_reports_zero_chunks(monkeypatch):
    async def broken_speak(text, voice=None, language=None):
        raise RuntimeError("rumik is down")
        yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(doubts, "stream_followup", _fake_llm)
    monkeypatch.setattr(doubts.followup_voice, "speak_chunks", broken_speak)
    monkeypatch.setattr(doubts.followup_voice, "prewarm", lambda *a, **k: None)
    monkeypatch.setattr(doubts, "_tutor_voice_for", lambda user_id: "drona")

    frames = _frames(doubts._followup_response(
        {"id": "d1"}, "d1", "u1", "why?", []))
    names = [n for n, _ in frames]

    # Zero chunks is the phone's cue to fetch /speak-stream instead of
    # sitting silent. The answer itself is untouched.
    assert dict(frames)["voice_done"]["chunks"] == 0
    assert names.count("step") == 2
    assert names[-1] == "done"


def test_an_answer_with_no_spoken_line_does_not_wait_for_a_voice(monkeypatch):
    def mute_llm(*_args, **_kwargs):
        yield "step", {"n": 1, "text": "just this"}

    called = []

    async def fake_speak(text, voice=None, language=None):
        called.append(text)
        yield 1, 1, b"x"

    monkeypatch.setattr(doubts, "stream_followup", mute_llm)
    monkeypatch.setattr(doubts.followup_voice, "speak_chunks", fake_speak)
    monkeypatch.setattr(doubts.followup_voice, "prewarm", lambda *a, **k: None)
    monkeypatch.setattr(doubts, "_tutor_voice_for", lambda user_id: "drona")

    frames = _frames(doubts._followup_response(
        {"id": "d1"}, "d1", "u1", "hm?", []))
    names = [n for n, _ in frames]

    assert not called
    assert "voice_done" not in names
    assert names[-1] == "done"
