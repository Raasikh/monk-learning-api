"""The /drona/session/{id}/live handshake: every refusal must CLOSE the socket.

A WebSocket handler that raises instead of closing costs more than the one
connection. Starlette logs the whole traceback, and a client that reconnects
turns that into a traceback per attempt — enough to fill Railway's 500-line
buffer and evict everything else. Two unrelated Snap failures were diagnosed
blind for exactly that reason: by the time anyone looked, the only thing left
in the log was this endpoint's stack.

`asyncio.run` rather than pytest-asyncio, which this project does not install.
"""
import asyncio

import pytest

from app.drona import live_session_ws


class _FakeWebSocket:
    """Records what the handler did instead of talking to a real client."""

    def __init__(self):
        self.accepted = False
        self.sent = []
        self.close_code = None
        self.query_params = {}

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code=1000):
        self.close_code = code


def _connect(session_id, monkeypatch, table=None):
    """Runs the handshake and returns the socket it acted on."""
    if table is not None:
        monkeypatch.setattr(live_session_ws.supabase, "table", table)
    ws = _FakeWebSocket()
    asyncio.run(live_session_ws.drona_live_session_ws(ws, session_id))
    return ws


def test_a_malformed_session_id_is_closed_not_raised(monkeypatch):
    """"verify" is not a UUID, and Postgres says so by raising.

    22P02 "invalid input syntax for type uuid" came from the session query,
    which sits BEFORE the `if not res_s.data` that closes an unknown session
    cleanly — so a non-UUID id escaped as an unhandled ASGI exception and
    printed a full traceback every time something retried it.
    """
    def never_queried(*_a, **_kw):
        raise AssertionError("a malformed id must be refused before the query")

    ws = _connect("verify", monkeypatch, table=never_queried)
    print(f"  close_code={ws.close_code} sent={ws.sent}")
    assert ws.close_code == 4004, "a malformed id is refused like an unknown one"
    assert ws.sent and "not found" in ws.sent[0]["message"].lower()


def test_a_session_id_that_is_not_a_string_at_all(monkeypatch):
    """Nothing about the path guarantees a usable value; None must not raise."""
    def never_queried(*_a, **_kw):
        raise AssertionError("should not reach the query")

    ws = _connect(None, monkeypatch, table=never_queried)
    assert ws.close_code == 4004


def test_a_supabase_failure_closes_1011_rather_than_raising(monkeypatch):
    """The other way this endpoint was throwing: the read itself failing.

    An HTTP/2 `ConnectionTerminated` from Supabase was filling the same log.
    1011 and not 4004 on purpose — this failure is ours, and a client that
    treats 4004 as permanent has to stay free to retry a server fault.
    """
    class _Boom:
        def select(self, *_a, **_kw):
            return self

        def eq(self, *_a, **_kw):
            return self

        def execute(self):
            raise RuntimeError("ConnectionTerminated error_code:0")

    ws = _connect("11111111-2222-3333-4444-555555555555",
                  monkeypatch, table=lambda *_a, **_kw: _Boom())
    print(f"  close_code={ws.close_code} sent={ws.sent}")
    assert ws.close_code == 1011, (
        "a server-side fault must not be reported as a permanent refusal"
    )


def test_a_well_formed_but_unknown_session_still_closes_4004(monkeypatch):
    """The behaviour that already existed, kept."""
    class _Empty:
        data = []

        def select(self, *_a, **_kw):
            return self

        def eq(self, *_a, **_kw):
            return self

        def execute(self):
            return self

    ws = _connect("11111111-2222-3333-4444-555555555555",
                  monkeypatch, table=lambda *_a, **_kw: _Empty())
    assert ws.close_code == 4004
    assert ws.accepted, "the socket is accepted before it can be told anything"
