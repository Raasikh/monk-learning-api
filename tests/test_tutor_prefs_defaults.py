"""`_tutor_prefs_for` must answer even when there is nothing to read.

This exists because it stopped doing that in production and nothing noticed.
`followup_voice` used to export DEFAULT_LANGUAGE; 87961f7 removed it along with
the cached opener that needed it, and `_tutor_prefs_for` kept reading
`followup_voice.DEFAULT_LANGUAGE`. Every voice follow-up by a student whose
last session carried no language — or who had no session at all — raised

    AttributeError: module 'app.followup_voice' has no attribute 'DEFAULT_LANGUAGE'

The whole suite stayed green, because the only paths that reach those two
lines are the ones where the read comes back empty or throws, and nothing
covered them. These are those two paths.
"""

from types import SimpleNamespace

import pytest

from app.routers import doubts as d


class _Res:
    def __init__(self, data):
        self.data = data


def _fake_supabase(result):
    """A chain that ignores every filter and answers with `result`."""
    class Q:
        def select(self, *_a, **_k): return self
        def eq(self, *_a, **_k): return self
        def order(self, *_a, **_k): return self
        def limit(self, *_a, **_k): return self
        def execute(self):
            if isinstance(result, Exception):
                raise result
            return _Res(result)
    return SimpleNamespace(table=lambda _t: Q())


def test_a_student_with_no_session_still_gets_a_voice_and_a_language(monkeypatch):
    monkeypatch.setattr(d, "supabase", _fake_supabase([]))
    voice, language = d._tutor_prefs_for("cccccccc-0000-0000-0000-000000000001")
    assert voice, "no voice to speak with"
    assert language, "no language to speak in"


def test_a_session_row_with_no_language_falls_back_rather_than_raising(monkeypatch):
    """The exact shape that broke: a real row, but `language` is NULL."""
    monkeypatch.setattr(d, "supabase",
                        _fake_supabase([{"tutor_voice": "male", "language": None}]))
    voice, language = d._tutor_prefs_for("cccccccc-0000-0000-0000-000000000001")
    assert voice == "male"
    assert language in ("english", "hinglish"), language


def test_a_failed_read_falls_back_rather_than_raising(monkeypatch):
    monkeypatch.setattr(d, "supabase", _fake_supabase(RuntimeError("postgrest is down")))
    voice, language = d._tutor_prefs_for("cccccccc-0000-0000-0000-000000000001")
    assert voice and language


def test_the_language_default_is_one_the_database_accepts():
    """`drona_sessions.language` has a check constraint. A default outside it
    would be written back and rejected at the far end of the call."""
    assert d.DEFAULT_LANGUAGE in ("english", "hinglish")
