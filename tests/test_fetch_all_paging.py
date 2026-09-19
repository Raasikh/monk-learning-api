"""Paging a table needs an order, and not every table's key is called `id`.

`fetch_all` paged with .range() and no ORDER BY. `.range(1000, 1999)` asks for
the second window of an order, and without an ORDER BY there is no defined order
to take a window of — Postgres returns whatever the chosen plan produces, and
two requests are two plans. The failure is not an error: it is a second page
that repeats rows the first already had, and therefore silently omits others.
Same shape as the 1000-row truncation this function exists to prevent.

The other half is that a blanket `.order("id")` would have been an outage.
`progress_config` (keyed by `version`) and `chapter_exam_weights` (keyed by
chapter_id + exam) have no `id` column at all, and both are read on /progress.
"""

from types import SimpleNamespace

import pytest

import app.db as db


class Recorder:
    """Pages a fixed list, recording the order and window asked for."""

    def __init__(self, rows, log):
        # NOT `self.order` — that would shadow the order() method below with a
        # list, and the builder call would raise "'list' object is not callable".
        self.rows, self.log, self.order_cols, self.window = rows, log, [], None

    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self

    def order(self, col, **_k):
        self.order_cols.append(col)
        return self

    def range(self, lo, hi):
        self.window = (lo, hi)
        return self

    def execute(self):
        self.log.append({"order": list(self.order_cols), "window": self.window})
        lo, hi = self.window
        return SimpleNamespace(data=self.rows[lo:hi + 1], count=None)


@pytest.fixture()
def paged(monkeypatch):
    calls = []
    total = db.POSTGREST_PAGE + 172          # two pages, second one short
    rows = [{"id": f"c{i:05d}", "name": f"concept {i}"} for i in range(total)]
    monkeypatch.setattr(db, "supabase",
                        SimpleNamespace(table=lambda _t: Recorder(rows, calls)))
    db.clear_taxonomy_cache()
    yield calls, total
    db.clear_taxonomy_cache()


def test_every_page_is_ordered_or_the_window_means_nothing(paged):
    calls, _total = paged
    db.fetch_all("concepts", "id, name")
    assert calls, "nothing was read"
    for call in calls:
        assert call["order"] == ["id"], f"page asked for {call['order']!r}"


def test_paging_returns_every_row_exactly_once(paged):
    calls, total = paged
    rows = db.fetch_all("concepts", "id, name")
    assert len(rows) == total
    assert len({r["id"] for r in rows}) == total, "a row repeated or went missing"
    assert len(calls) == 2, [c["window"] for c in calls]


def test_a_table_whose_key_is_not_id_passes_its_own(paged):
    """progress_config has no `id`. A default of ("id",) would raise against
    the real database, so the caller has to say what its key is."""
    calls, _total = paged
    db.fetch_all("progress_config", "config", order_by=("version",), active=True)
    assert calls[0]["order"] == ["version"]


def test_a_composite_key_orders_by_both_parts(paged):
    """chapter_exam_weights is unique on (chapter_id, exam); either column
    alone leaves ties, and ties inside a page boundary are unordered again."""
    calls, _total = paged
    db.fetch_all("chapter_exam_weights", "chapter_id, exam, avg_marks",
                 order_by=("chapter_id", "exam"))
    assert calls[0]["order"] == ["chapter_id", "exam"]


def test_the_cache_key_includes_the_order(paged):
    """Two orders are two different lists. Sharing a cache entry between them
    would hand a caller rows sorted by somebody else's key."""
    calls, _total = paged
    db.fetch_all_cached("concepts", "id, name", order_by=("id",))
    first = len(calls)
    db.fetch_all_cached("concepts", "id, name", order_by=("name",))
    assert len(calls) > first, "a different order was served from the same cache entry"
