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
    def range(self, lo, hi):
        self.filters.append(("range", lo, hi)); self._window = (lo, hi); return self

    def execute(self):
        self.log.append((self.table, list(self.filters)))
        data = self.rows(self.table, self.filters)
        window = getattr(self, "_window", None)
        if window:
            lo, hi = window
            data = data[lo:hi + 1]
        return SimpleNamespace(data=data, count=None)


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


def test_paging_gets_the_whole_pool_not_the_first_thousand(monkeypatch):
    """PostgREST caps a response at 1000 rows and does not say so. There are
    2,628-3,092 servable rows per subject, so a plain read left two thirds of
    the bank unreachable — a question a student could never be served."""
    import app.db as db
    page_size = db.POSTGREST_PAGE
    total = page_size * 2 + 137          # three pages, last one short
    all_rows = [{"id": f"q{i:06d}", "chapter_id": CH11, "chapter_name": "U&M",
                 "concept": "c", "question_type": "single_correct", "difficulty": 2,
                 "target_exams": ["jee"], "discipline": None} for i in range(total)]
    ranges = []

    class Q:
        def select(self, *_a, **_k): return self
        def eq(self, *_a, **_k): return self
        def is_(self, *_a, **_k): return self
        def or_(self, *_a, **_k): return self
        def ilike(self, *_a, **_k): return self
        def order(self, *_a, **_k): return self
        def range(self, lo, hi):
            ranges.append((lo, hi)); self._slice = (lo, hi); return self
        def execute(self):
            lo, hi = self._slice
            return SimpleNamespace(data=all_rows[lo:hi + 1], count=None)

    monkeypatch.setattr(prac, "supabase", SimpleNamespace(table=lambda _t: Q()))
    rows = prac._fetch_pool("physics", None)

    assert len(rows) == total, f"got {len(rows)} of {total}"
    assert len({r["id"] for r in rows}) == total, "paging repeated or skipped rows"
    assert len(ranges) == 3, ranges


def test_the_pool_read_is_ordered_or_paging_cannot_be_trusted(monkeypatch):
    """`.range()` without an ORDER BY asks for 'rows 1000-1999' of an
    unspecified order, so a different plan between pages can repeat or skip."""
    ordered = []

    class Q:
        def select(self, *_a, **_k): return self
        def eq(self, *_a, **_k): return self
        def is_(self, *_a, **_k): return self
        def or_(self, *_a, **_k): return self
        def ilike(self, *_a, **_k): return self
        def order(self, col, **_k): ordered.append(col); return self
        def range(self, *_a): return self
        def execute(self): return SimpleNamespace(data=[], count=None)

    monkeypatch.setattr(prac, "supabase", SimpleNamespace(table=lambda _t: Q()))
    prac._fetch_pool("physics", None)
    assert ordered == ["id"], f"paged read ordered by {ordered!r}"


def test_warming_fills_the_pools_with_no_request_involved(monkeypatch):
    """A fill is ~2.3s now. No student should be the one to pay it."""
    calls = []

    class Q:
        def select(self, *_a, **_k): return self
        def eq(self, *_a, **_k): return self
        def is_(self, *_a, **_k): return self
        def or_(self, *_a, **_k): return self
        def ilike(self, *_a, **_k): return self
        def order(self, *_a, **_k): return self
        def range(self, *_a): return self
        def execute(self):
            calls.append(1)
            return SimpleNamespace(data=[{"id": "q1", "chapter_id": CH11,
                                          "chapter_name": "U&M", "concept": "c",
                                          "question_type": "single_correct",
                                          "difficulty": 2, "target_exams": ["jee"],
                                          "discipline": None}], count=None)

    monkeypatch.setattr(prac, "supabase", SimpleNamespace(table=lambda _t: Q()))
    client = fakeredis.FakeRedis(decode_responses=True)
    store._reset_sync_for_tests(client)
    prac.clear_candidate_cache()
    try:
        prac.warm_candidate_pools()
        keys = client.keys("practice:pool:*")
        assert len(keys) == 4, f"warmed {keys}"
        # And a worker that never warmed finds them already there.
        prac.clear_candidate_cache()
        before = len(calls)
        rows, tier, share = prac._cached_pool("physics", None)
        assert tier == "redis", tier
        assert len(calls) == before, "a warmed pool still went to Supabase"
        assert share is None and rows
    finally:
        store._reset_sync_for_tests(None)
        store._sync_checked = False
        prac.clear_candidate_cache()


def test_a_pool_cached_by_an_older_version_is_not_reused(monkeypatch):
    """This happened in production. The paged read shipped sharing a key with
    the truncated read, so it found the previous deploy's 1000-row pools in
    Redis, accepted them as valid, and kept serving a third of the bank:

        [PRACTICE WARM] chemistry   pool=redis rows=1000
        [PRACTICE WARM] mathematics pool=redis rows=1000

    A TTL is not a migration. The version in the key is what makes an old entry
    a key nobody asks for rather than a stale value to be trusted.
    """
    import json

    class Q:
        def select(self, *_a, **_k): return self
        def eq(self, *_a, **_k): return self
        def is_(self, *_a, **_k): return self
        def or_(self, *_a, **_k): return self
        def ilike(self, *_a, **_k): return self
        def order(self, *_a, **_k): return self
        def range(self, *_a): return self
        def execute(self):
            return SimpleNamespace(data=[{"id": "fresh", "chapter_id": CH11,
                                          "chapter_name": "U&M", "concept": "c",
                                          "question_type": "single_correct",
                                          "difficulty": 2, "target_exams": ["jee"],
                                          "discipline": None}], count=None)

    monkeypatch.setattr(prac, "supabase", SimpleNamespace(table=lambda _t: Q()))
    client = fakeredis.FakeRedis(decode_responses=True)
    store._reset_sync_for_tests(client)
    prac.clear_candidate_cache()
    try:
        # Exactly what the previous deploy left behind: the old unversioned key.
        client.set("practice:pool:physics|", json.dumps([{"id": "stale"}]), ex=600)

        rows, tier, _share = prac._cached_pool("physics", None)
        assert tier == "supabase", f"served from {tier} — the old key was reused"
        assert [r["id"] for r in rows] == ["fresh"], rows
    finally:
        store._reset_sync_for_tests(None)
        store._sync_checked = False
        prac.clear_candidate_cache()


def test_a_forced_warm_refetches_rather_than_trusting_its_own_cache(monkeypatch):
    """The refresh loop exists because warming once at startup leaves the pools
    warm for one TTL and cold for the rest of the day — measured in production:
    warmed 18:46:40, expired 18:56, a student at 19:17 paid 4206ms to refill.

    A refresh pass that accepted the cached copy would be a no-op, and the loop
    would keep the numbers looking healthy while doing nothing."""
    fetches = []

    class Q:
        def select(self, *_a, **_k): return self
        def eq(self, *_a, **_k): return self
        def is_(self, *_a, **_k): return self
        def or_(self, *_a, **_k): return self
        def ilike(self, *_a, **_k): return self
        def order(self, *_a, **_k): return self
        def range(self, *_a): return self
        def execute(self):
            fetches.append(1)
            return SimpleNamespace(data=[{"id": "q1", "chapter_id": CH11,
                                          "chapter_name": "U&M", "concept": "c",
                                          "question_type": "single_correct",
                                          "difficulty": 2, "target_exams": ["jee"],
                                          "discipline": None}], count=None)

    monkeypatch.setattr(prac, "supabase", SimpleNamespace(table=lambda _t: Q()))
    client = fakeredis.FakeRedis(decode_responses=True)
    store._reset_sync_for_tests(client)
    prac.clear_candidate_cache()
    try:
        prac.warm_candidate_pools()                 # fills
        after_first = len(fetches)
        assert after_first > 0

        prac.warm_candidate_pools()                 # unforced: cached, no work
        assert len(fetches) == after_first, "an unforced pass refetched"

        prac.warm_candidate_pools(force=True)       # forced: must refetch
        assert len(fetches) > after_first, "a forced pass did not refetch"
    finally:
        store._reset_sync_for_tests(None)
        store._sync_checked = False
        prac.clear_candidate_cache()


def test_the_shared_copy_outlives_the_refresh_interval(monkeypatch):
    """If the Redis TTL were shorter than the refresh interval, the entry would
    be gone for part of every cycle and a student would land in the gap."""
    assert prac._POOL_SHARE_TTL_S > prac._POOL_REFRESH_S * 2, (
        f"share TTL {prac._POOL_SHARE_TTL_S}s vs refresh {prac._POOL_REFRESH_S}s"
    )


def test_the_refresh_beats_the_local_ttl(monkeypatch):
    """The local copy has to be replaced before it expires, or every cycle has a
    window where the worker falls back to Redis for no reason."""
    assert prac._POOL_REFRESH_S < prac._CANDIDATE_TTL_S, (
        f"refresh {prac._POOL_REFRESH_S}s vs local TTL {prac._CANDIDATE_TTL_S}s"
    )
