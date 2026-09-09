"""GET /drona/chapter/{id}/figures — the list the client downloads before class."""
import app.routers.drona as drona
from app import storage_r2


def _row(slug, **kw):
    r = {"asset_slug": slug, "concept_slug": slug.rsplit("--", 1)[0],
         "sub_index": 0, "concept_id": "c1", "r2_key": f"concept-assets/{slug}.png",
         "content_type": "image/png", "width": 896, "height": 560, "bytes": 1234,
         "master_sha256": "a" * 64, "rendition_2x_sha256": "b" * 64,
         "manifest_status": storage_r2.ASSET_APPROVED_STATUS}
    r.update(kw)
    return r


def test_it_returns_only_this_chapters_rows(monkeypatch):
    """The whole point of the endpoint: one chapter's art, not the corpus.

    A client that received every asset would download 113 files to show three.
    """
    seen = {}

    def fake_fetch_all(table, cols, **eq):
        seen["table"], seen["eq"] = table, eq
        return [_row("bio11-ch7-cockroach--morphology--a")]

    monkeypatch.setattr(drona, "fetch_all", fake_fetch_all)
    out = drona.get_chapter_figures("chap-7", user_id="u1")
    assert seen["table"] == "concept_assets"
    # Filtered in the QUERY, not after: filtering client-side would read the
    # whole table through PostgREST's 1000-row cap and silently lose the tail.
    assert seen["eq"] == {"chapter_id": "chap-7"}
    assert out["chapter_id"] == "chap-7"
    assert [a["asset_slug"] for a in out["assets"]] == ["bio11-ch7-cockroach--morphology--a"]


def test_unapproved_rows_are_not_offered(monkeypatch):
    monkeypatch.setattr(drona, "fetch_all", lambda *a, **k: [
        _row("good--a"),
        _row("queued--a", manifest_status="svg-queue"),
    ])
    out = drona.get_chapter_figures("chap-7", user_id="u1")
    assert [a["asset_slug"] for a in out["assets"]] == ["good--a"]


def test_a_set_comes_back_in_figure_order(monkeypatch):
    monkeypatch.setattr(drona, "fetch_all", lambda *a, **k: [
        _row("frog--c", concept_slug="frog", sub_index=2),
        _row("frog--a", concept_slug="frog", sub_index=0),
        _row("frog--b", concept_slug="frog", sub_index=1),
    ])
    out = drona.get_chapter_figures("chap-7", user_id="u1")
    assert [a["sub_index"] for a in out["assets"]] == [0, 1, 2]


def test_every_row_carries_the_hash_the_client_caches_on(monkeypatch):
    monkeypatch.setattr(drona, "fetch_all", lambda *a, **k: [_row("a--a")])
    out = drona.get_chapter_figures("chap-7", user_id="u1")
    a = out["assets"][0]
    # bytes is NOT a version: two different plates can be the same length.
    for key in ("asset_slug", "r2_key", "bytes", "master_sha256",
                "rendition_2x_sha256", "width", "height"):
        assert key in a, f"{key} missing — the client needs it to fetch and verify"


def test_an_unreadable_table_is_an_empty_list_not_a_500(monkeypatch):
    """A chapter whose figures cannot be listed is a class that draws no
    figures — which the client already handles. A 500 would stop the class
    from starting at all, which is strictly worse than a plain board."""
    def boom(*a, **k):
        raise RuntimeError("PostgREST is down")
    monkeypatch.setattr(drona, "fetch_all", boom)
    out = drona.get_chapter_figures("chap-7", user_id="u1")
    assert out == {"chapter_id": "chap-7", "assets": []}
