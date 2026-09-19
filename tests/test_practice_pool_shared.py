"""The candidate pool is shared between workers, not re-fetched by each.

WEB_CONCURRENCY is 4. An in-process dict is therefore four independent copies
of the same 278KB of rows, each paying its own ~800ms Supabase fetch — and at
low traffic a worker can go a whole TTL without being asked for the same
subject twice, which is exactly where a per-process cache helps least.

So the pool has a second tier in Redis. These tests are about the case that
motivated it: a worker that has never served this subject must find the pool
already there, and must not go to Supabase for it.

The in-process tier is cleared between the two serves to stand in for "a
different worker" — that dict is the only thing distinguishing one process from
another here, so emptying it is a faithful stand-in.
"""

from types import SimpleNamespace
from typing import List, Tuple

import fakeredis
import pytest

import app.redis_store as store
from app.routers import practice as prac

CH11 = "11111111-1111-1111-1111-111111111111"
QID = "aaaaaaaa-0000-0000-0000-000000000001"
USER = "cccccccc-0000-0000-0000-000000000001"


class FakeQuery:
    def __init__(self, table, log, rows):
        self.table, self.log, self.rows, self.filters = table, log, rows, []

    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.filters.append(("eq", k, v)); return self
    def is_(self, k, v): self.filters.append(("is", k, v)); return self
    def or_(self, e): self.filters.append(("or", e)); return self
    def ilike(self, k, v): self.filters.append(("ilike", k, v)); return self
    def order(self, k, desc=False): self.filters.append(("order", k, desc)); return self
    def limit(self, n): self.filters.append(("limit", n)); return self

    def execute(self):
        self.log.append((self.table, list(self.filters)))
        return SimpleNamespace(data=self.rows(self.table, self.filters), count=None)


@pytest.fixture()
def wired(monkeypatch):
    questions = [{
        "id": QID, "question_type": "single_correct", "chapter_id": CH11,
        "chapter_name": "Units & Measurements", "concept": "Significant Figures",
        "difficulty": 2, "target_exams": ["jee"], "discipline": None,
    }]
    calls: List[Tuple[str, list]] = []

    def rows(table, filters):
        if table == "practice_attempts":
            return []
        if table == "questions":
            if [f for f in filters if f[0] == "eq" and f[1] == "id"]:
                return [{**questions[0], "question_text": "A steel rule reads 12.0 cm.",
                         "options": ["a", "b", "c", "d"], "diagram": None}]
            return questions
        return []

    monkeypatch.setattr(prac, "supabase",
                        SimpleNamespace(table=lambda t: FakeQuery(t, calls, rows)))
    monkeypatch.setattr(prac, "fetch_all_cached", lambda table, _sel="", **_kw: (
        [{"id": CH11, "name": "Units & Measurements", "subject": "physics",
          "class_level": 11}] if table == "chapters" else []))
    monkeypatch.setattr(prac, "is_quality_question", lambda _r: True)
    monkeypatch.setattr(prac, "resolve_display_concept", lambda _q, raw: raw)

    client = fakeredis.FakeRedis(decode_responses=True)
    store._reset_sync_for_tests(client)
    prac.clear_candidate_cache()

    tasks = SimpleNamespace(added=[])
    tasks.add_task = lambda fn, *a: tasks.added.append((fn, a))
    body = prac.PracticeNextRequest(exam="jee", class_level="11", subject="physics")

    def serve(run_background=True):
        """Serves, then runs whatever was deferred — which is what FastAPI does
        after the response is sent. Tests that care about the share landing must
        let it run; tests about the request path itself must not."""
        out = prac.get_next_question(body, tasks, user_id=USER)
        if run_background:
            for fn, args in tasks.added:
                fn(*args)
            tasks.added.clear()
        return out

    yield serve, calls, client, tasks
    store._reset_sync_for_tests(None)
    store._sync_checked = False
    prac.clear_candidate_cache()


def _scans(calls):
    """Candidate scans only — the by-id reads are the chosen row, not the pool."""
    return [f for t, f in calls
            if t == "questions" and not any(x[0] == "eq" and x[1] == "id" for x in f)]


def test_a_cold_worker_reads_the_pool_from_redis_not_supabase(wired):
    serve, calls, _client, _tasks = wired
    serve()
    assert len(_scans(calls)) == 1, "the first serve should fetch the pool once"

    # A different worker: same Redis, empty local dict.
    prac.clear_candidate_cache()
    result = serve()

    assert len(_scans(calls)) == 1, "a cold worker went back to Supabase"
    assert result["question_id"] == QID, "the shared pool did not serve a question"


def test_the_pool_is_actually_written_to_redis_under_a_scoped_key(wired):
    serve, _calls, client, _tasks = wired
    serve()
    keys = client.keys("practice:pool:*")
    assert keys, "nothing was shared"
    # Subject-scoped: physics must not be served out of biology's pool.
    assert any("physics" in k for k in keys), keys


def test_the_pool_expires_so_a_bank_import_is_picked_up(wired):
    serve, _calls, client, _tasks = wired
    serve()
    key = client.keys("practice:pool:*")[0]
    ttl = client.ttl(key)
    assert 0 < ttl <= prac._CANDIDATE_TTL_S, f"ttl was {ttl}"


def test_with_no_redis_it_still_serves_from_its_own_memory(wired):
    """REDIS_URL unset is the laptop case, and the documented degradation."""
    serve, calls, _client, _tasks = wired
    store._reset_sync_for_tests(None)
    serve()
    before = len(_scans(calls))
    serve()
    assert len(_scans(calls)) == before, "the in-process tier stopped working"


def test_the_share_is_deferred_not_paid_for_by_the_student(wired):
    """Serialising ~278KB and PUTting it are real work. Doing them before
    returning made a cold call slower than it was with no cache at all — the
    student paying to warm a pool they were not going to read again."""
    serve, _calls, client, tasks = wired
    serve(run_background=False)

    assert not client.keys("practice:pool:*"), "the share happened on the request path"
    assert tasks.added, "the share was not deferred either — it was dropped"

    for fn, args in tasks.added:
        fn(*args)
    assert client.keys("practice:pool:*"), "the deferred share never landed"
