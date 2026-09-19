"""/practice/next assembles a question end to end.

This file exists for the same reason test_progress_endpoint.py does: the
endpoint had NO coverage at all, and it is the tap behind every practice
question. It was then restructured for latency — the attempt history and the
candidate pool now go out in one wave instead of one after the other, the
chosen row and its display concept in another, and `subject` is matched with
`=` rather than ILIKE so the index in migration 0052 can be used.

Every one of those changes is invisible to a unit test of the helpers around
it, and any of them could return the wrong question while the suite stayed
green. So this does the dumbest useful thing: serve one question and look at
it, and look at what was actually asked of the database on the way.
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import pytest

from app.routers import practice as prac

CH11 = "11111111-1111-1111-1111-111111111111"
UNSEEN = "aaaaaaaa-0000-0000-0000-00000000unse".replace("unse", "0001")
STALE_WRONG = "aaaaaaaa-0000-0000-0000-000000000002"
USER = "cccccccc-0000-0000-0000-000000000001"


class FakeQuery:
    """Records the filters a call actually applied, then answers from a table."""

    def __init__(self, table: str, log: List[Tuple[str, list]], rows):
        self.table = table
        self.log = log
        self.rows = rows
        self.filters: list = []

    def select(self, _cols: str = "", **_kw):
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self

    def is_(self, key, value):
        self.filters.append(("is", key, value))
        return self

    def or_(self, expr):
        self.filters.append(("or", expr))
        return self

    def ilike(self, key, value):
        self.filters.append(("ilike", key, value))
        return self

    def order(self, key, desc: bool = False):
        self.filters.append(("order", key, desc))
        return self

    def limit(self, n):
        self.filters.append(("limit", n))
        return self

    def range(self, lo, hi):
        # The candidate pool is read in pages now. Slicing here is what lets a
        # short final page end the loop instead of spinning forever.
        self.filters.append(("range", lo, hi))
        self._window = (lo, hi)
        return self

    def execute(self):
        self.log.append((self.table, list(self.filters)))
        data = self.rows(self.table, self.filters)
        window = getattr(self, "_window", None)
        if window:
            lo, hi = window
            data = data[lo:hi + 1]
        return SimpleNamespace(data=data, count=None)


@pytest.fixture
def served(monkeypatch):
    """One physics chapter, two servable questions: one never attempted, one
    answered wrongly long enough ago to be Tier-1 eligible again."""
    questions = [
        {"id": UNSEEN, "question_type": "single_correct", "chapter_id": CH11,
         "chapter_name": "Units & Measurements", "concept": "Significant Figures",
         "difficulty": 2, "target_exams": ["jee"], "discipline": None},
        {"id": STALE_WRONG, "question_type": "single_correct", "chapter_id": CH11,
         "chapter_name": "Units & Measurements", "concept": "Error Analysis",
         "difficulty": 3, "target_exams": ["jee"], "discipline": None},
    ]
    # 30 attempts, the oldest of which is STALE_WRONG answered incorrectly, so
    # `attempts_since` clears the 21-attempt gate.
    attempts = [{"id": f"att-{i}", "question_id": STALE_WRONG if i == 0 else "other",
                 "is_correct": False if i == 0 else True,
                 "created_at": f"2026-09-{(i % 27) + 1:02d}T00:00:00Z"}
                for i in range(30)]

    calls: List[Tuple[str, list]] = []

    def rows(table: str, filters: list):
        if table == "practice_attempts":
            # Handler asks newest-first and reverses; order does not matter to
            # the assertions, only that it got a full window.
            return list(reversed(attempts))
        if table == "questions":
            by_id = [f for f in filters if f[0] == "eq" and f[1] == "id"]
            if by_id:
                wanted = by_id[0][2]
                base = next(q for q in questions if q["id"] == wanted)
                # The full-row read carries what the quality gate needs.
                return [{**base, "question_text": "A steel rule reads 12.0 cm.",
                         "options": ["a", "b", "c", "d"], "diagram": None}]
            return questions
        return []

    monkeypatch.setattr(prac, "supabase",
                        SimpleNamespace(table=lambda t: FakeQuery(t, calls, rows)))
    monkeypatch.setattr(prac, "fetch_all_cached", lambda table, _sel="", **_kw: (
        [{"id": CH11, "name": "Units & Measurements", "subject": "physics",
          "class_level": 11}] if table == "chapters" else []
    ))
    monkeypatch.setattr(prac, "is_quality_question", lambda _row: True)
    monkeypatch.setattr(prac, "resolve_display_concept",
                        lambda _qid, raw: f"curated::{raw}")

    # The candidate pool is a module-level cache and outlives a test. Without
    # this, whichever test ran first serves every later one from memory and the
    # assertions about what was asked of the database quietly pass on nothing.
    prac.clear_candidate_cache()

    tasks = SimpleNamespace(added=[], add_task=lambda fn, *a: tasks.added.append((fn, a)))
    body = prac.PracticeNextRequest(exam="jee", class_level="11", subject="physics")

    def serve():
        return prac.get_next_question(body, tasks, user_id=USER)

    result = serve()
    return result, calls, tasks, serve


def test_it_serves_a_real_question(served):
    result, _calls, _tasks, _again = served
    assert "exhausted" not in result, result
    assert result["question_id"] in {UNSEEN, STALE_WRONG}
    assert result["question_text"]


def test_the_display_concept_is_resolved_not_the_raw_tag(served):
    """The concept read now runs beside the full-row read rather than after it.
    If its future were never awaited — or awaited before it was assigned — this
    is the field that would come back None."""
    result, _calls, _tasks, _again = served
    assert str(result["concept"]).startswith("curated::")


def test_subject_is_matched_with_eq_so_the_index_can_be_used(served):
    """ILIKE on a text column cannot use the btree index migration 0052 adds.
    This is the assertion that keeps the two in step."""
    _result, calls, _tasks, _again = served
    candidate_calls = [
        f for t, f in calls
        if t == "questions" and not any(x[0] == "eq" and x[1] == "id" for x in f)
    ]
    assert candidate_calls, "no candidate scan was issued"
    scan = candidate_calls[0]
    assert ("eq", "subject", "physics") in scan
    assert not [x for x in scan if x[0] == "ilike" and x[1] == "subject"]


def test_the_attempt_window_is_bounded_and_newest_first(served):
    """Unbounded and ascending, PostgREST silently returned the OLDEST 1000 —
    which zeroed `used_today` and disabled the daily cap for heavy users."""
    _result, calls, _tasks, _again = served
    attempts = [f for t, f in calls if t == "practice_attempts"]
    assert attempts, "the attempt history was never read"
    assert ("order", "created_at", True) in attempts[0]
    assert ("limit", prac.POSTGREST_PAGE) in attempts[0]


def test_serving_is_recorded_in_the_background_not_inline(served):
    """The student waits on none of the serve bookkeeping."""
    _result, _calls, tasks, _again = served
    assert tasks.added, "question.served was never recorded"


def _candidate_scans(calls):
    return [f for t, f in calls
            if t == "questions" and not any(x[0] == "eq" and x[1] == "id" for x in f)]


def test_the_candidate_pool_is_fetched_once_not_per_question(served):
    """The pool is the same rows for every student sitting the subject, and
    fetching it cost ~800ms of the ~1.8s this endpoint used to take. The second
    question must not pay for it again."""
    _result, calls, _tasks, serve_again = served
    assert len(_candidate_scans(calls)) == 1
    serve_again()
    assert len(_candidate_scans(calls)) == 1, "the pool was re-fetched"


def test_the_attempt_history_is_never_cached(served):
    """The pool is content; the history is the student. Caching the second
    would serve a question they just answered — so every call re-reads it."""
    _result, calls, _tasks, serve_again = served
    before = len([f for t, f in calls if t == "practice_attempts"])
    serve_again()
    after = len([f for t, f in calls if t == "practice_attempts"])
    assert after == before + 1, "attempts came from a cache"
