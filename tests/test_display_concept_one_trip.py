"""The display concept costs one round trip, not a table.

`resolve_display_concept` used to read `question_concepts` and then call
fetch_all_cached("concepts", "id, name") to look the name up in a dict — 1,172
rows fetched to resolve one of them. Cached, that was free on a warm worker and
**1753ms on a cold one**, measured against production. With WEB_CONCURRENCY=4
there are four workers to warm and a 600s TTL to lose it to, and it showed up
as a 2284ms second wave on a call whose candidate pool had already come from
Redis — nothing else left to blame.

The name is embedded over the concept_id foreign key now. The assertion that
keeps it that way is the negative one: no table-wide fetch.
"""

from types import SimpleNamespace

import pytest

from app.routers import practice as prac

QID = "78df4c90-0000-0000-0000-000000000001"


def _wire(monkeypatch, data, *, raises=False):
    """A question_concepts read that answers with `data`, and a canary on
    fetch_all_cached so a reintroduced table fetch fails loudly."""
    touched = []

    class Q:
        def select(self, *_a, **_k): return self
        def eq(self, *_a, **_k): return self
        def limit(self, *_a, **_k): return self
        def execute(self):
            if raises:
                raise RuntimeError("postgrest is down")
            return SimpleNamespace(data=data)

    monkeypatch.setattr(prac, "supabase", SimpleNamespace(table=lambda _t: Q()))

    def canary(table, *_a, **_k):
        touched.append(table)
        return []

    monkeypatch.setattr(prac, "fetch_all_cached", canary)
    return touched


def test_the_curated_name_wins_over_the_legacy_tag(monkeypatch):
    touched = _wire(monkeypatch, [{"concept_id": "c1", "concepts": {"name": "Collisions"}}])
    assert prac.resolve_display_concept(QID, "legacy-tag") == "Collisions"
    assert "concepts" not in touched, "the whole concepts table was fetched again"


def test_a_to_many_embed_is_also_read(monkeypatch):
    """Whether PostgREST infers to-one or to-many depends on how the FK is
    declared, and it has been seen both ways. A list must not read as no name."""
    _wire(monkeypatch, [{"concept_id": "c1", "concepts": [{"name": "Collisions"}]}])
    assert prac.resolve_display_concept(QID, "legacy-tag") == "Collisions"


def test_an_uncurated_question_keeps_its_legacy_tag(monkeypatch):
    """Subjects that were never curated have no question_concepts row, and must
    keep showing the free-text tag rather than losing their concept name."""
    _wire(monkeypatch, [])
    assert prac.resolve_display_concept(QID, "legacy-tag") == "legacy-tag"


def test_a_row_with_no_embedded_concept_keeps_the_legacy_tag(monkeypatch):
    _wire(monkeypatch, [{"concept_id": "c1", "concepts": None}])
    assert prac.resolve_display_concept(QID, "legacy-tag") == "legacy-tag"


def test_a_failed_read_keeps_the_legacy_tag_rather_than_raising(monkeypatch):
    """This runs inside the wave that serves the question. Raising here would
    turn a cosmetic lookup into a failed practice question."""
    _wire(monkeypatch, None, raises=True)
    assert prac.resolve_display_concept(QID, "legacy-tag") == "legacy-tag"
