"""A plan authored by the FALLBACK path is the same lesson, not a lesser one.

`create_plan_with_llm` is taken when `create_plan_streaming` raises. It
authored every segment in one call and inserted them as-is, which skipped the
per-segment slot-1/slot-4 board pass the streaming path runs and stamped no
`_status`. Measured on chemistry 12 ch8
'reactions-of-carbonyl-compounds-with-ammonia-derivatives', whose streaming
author died on a "Server disconnected" (2026-09-10):

  * its 6 segments carried no `example_widget_precompute` KEY AT ALL — so
    there was no record of whether anything had been asked, which is exactly
    the three-way ambiguity that key exists to remove: not-eligible, asked-
    and-declined, and answered-but-gated are three different facts with three
    different owners, and an absent key tells them apart from nothing;
  * `_plan_is_complete` reads an absent `_status` as complete, so the row was
    served to students forever and never regenerated.

WHAT THIS DEFECT IS **NOT**, corrected 2026-09-11 after repairing that row.
The first write-up of this — including commit 48926b5's message — claimed the
plan lacked precomputed WIDGET PAYLOADS because of the fallback, and that its
siblings had them. That was wrong, and wrong in the direction of blaming this
bug for someone else's verdict. The concept is `med` confidence in the
archetype column, and the server routes on `high` only, so it gets no
precomputed widget under EITHER authoring path. Repairing it through the
fixed path proves the distinction precisely: all 6 segments now carry the
precompute key, and payloads are still 0 — the key records `not_asked`, which
is the honest answer, where before there was silence. (The chapter is 6 high,
8 med, 1 low, so "its 14 siblings served precomputed widgets" was also
arithmetically impossible.)

The fallback's real damage is the two bullets above: no record, and a plan
that reads as finished. Both are fixed and pinned below.
"""
import app.drona.planner as planner


def _plan(n=6):
    # create_plan_with_llm validates before inserting, so by the time the fill
    # runs the plan is already valid — including wrapup_points matching the
    # segment count. The fixture has to be valid for the same reason.
    return {
        "topic": "t",
        "segments": [_segment(i) for i in range(n)],
        "wrapup_points": [f"wrap {i}" for i in range(n)],
    }


def _segment(i):
    # Must satisfy validate_plan_json — the fill validates before stamping, so
    # a fixture that could not pass validation would make this file green
    # against a plan the real path would refuse.
    return {
        "objective": f"objective {i}",
        "teaching_notes": f"notes {i}",
        "board_content": [f"line {i}.{j}" for j in range(9)],
        "checkpoint": {
            "question": f"question {i}?",
            "model_answer": f"answer {i}",
            "rubric": f"rubric {i}",
            "expected_misconceptions": [f"m{i}a", f"m{i}b"],
        },
    }


class _FakeTable:
    """Minimal PostgREST stand-in recording the update payload."""

    def __init__(self, store):
        self.store = store
        self._payload = None

    def select(self, *_a, **_k):
        return self

    def update(self, payload):
        self._payload = payload
        return self

    def eq(self, *_a, **_k):
        return self

    def execute(self):
        if self._payload is not None:
            self.store["updated"] = self._payload
            self._payload = None
            return type("R", (), {"data": [{"id": "plan-1"}]})()
        return type("R", (), {"data": [{"plan_json": self.store["plan_json"]}]})()


def _install(monkeypatch, store, attach):
    monkeypatch.setattr(planner, "supabase",
                        type("S", (), {"table": lambda _s, _n: _FakeTable(store)})())
    monkeypatch.setattr(planner, "_attach_segment_board", attach)


def test_every_segment_gets_the_board_pass(monkeypatch):
    store = {"plan_json": _plan()}
    touched = []

    def attach(segment, *_a, **_k):
        touched.append(segment["objective"])
        # What the real one records on every segment it touches.
        segment[planner.WIDGET_PRECOMPUTE_KEY] = {"status": "not_asked"}
        return "not_asked"

    _install(monkeypatch, store, attach)
    planner._attach_boards_to_authored_plan(
        "plan-1", {"id": "c", "subject": "chemistry"}, "Sub", "sub-key", None)

    # Every segment, not just the first — the streaming path boards all of
    # them, and a fallback that boarded only segment 1 would reproduce the
    # defect in a subtler form.
    assert touched == [f"objective {i}" for i in range(6)]


def test_the_plan_is_stamped_complete(monkeypatch):
    store = {"plan_json": _plan()}
    _install(monkeypatch, store,
             lambda seg, *a, **k: seg.__setitem__(planner.WIDGET_PRECOMPUTE_KEY,
                                                  {"status": "not_asked"}))

    planner._attach_boards_to_authored_plan(
        "plan-1", {"id": "c", "subject": "chemistry"}, "Sub", "sub-key", None)

    written = store["updated"]["plan_json"]
    assert written[planner.PLAN_STATUS_KEY] == "complete"
    assert written[planner.PLAN_EXPECTED_KEY] == 6
    assert planner._plan_is_complete(written)


def test_a_failed_board_fill_marks_the_plan_failed(monkeypatch):
    """It must not leave a half-boarded plan looking complete.

    Without this the fill could die partway and the row would keep whatever
    `_status` it had — `partial` — which at least regenerates. Marking it
    failed is what makes get_or_create_plan regenerate it IMMEDIATELY rather
    than waiting out the 300s grace window.
    """
    store = {"plan_json": _plan()}
    marked = {}

    def boom(*_a, **_k):
        raise RuntimeError("board pass exploded")

    _install(monkeypatch, store, boom)
    monkeypatch.setattr(planner, "_mark_plan_failed",
                        lambda pid, reason: marked.update(id=pid, reason=reason))

    # Never raises: a detached thread that raises takes the failure with it.
    planner._attach_boards_to_authored_plan(
        "plan-1", {"id": "c", "subject": "chemistry"}, "Sub", "sub-key", None)

    assert marked["id"] == "plan-1"
    assert "board pass exploded" in marked["reason"]
    assert "updated" not in store  # nothing was stamped complete


def test_an_unstamped_plan_would_read_as_complete():
    """The reason the stamp matters, pinned as its own fact.

    `_plan_is_complete` defaults an ABSENT `_status` to complete, for legacy
    rows. That default is why the fallback's omission was invisible rather
    than loud — the plan was not merely unmarked, it was actively treated as
    finished by every reader.
    """
    assert planner._plan_is_complete({"segments": []}) is True
    assert planner._plan_is_complete({"_status": "partial"}) is False


def test_both_paths_agree_on_the_status_vocabulary():
    # The fallback stamps "partial" then "complete"; the streaming path uses
    # the same two words. If either drifts, plans authored one way stop being
    # readable by code written for the other.
    import inspect
    # Read as SOURCE on purpose: both paths reference the constant by name,
    # so the value cannot be compared at runtime without actually authoring a
    # plan. What is being pinned is that neither path hard-codes a different
    # word than the other.
    stream_src = inspect.getsource(planner.create_plan_streaming)
    assert 'PLAN_STATUS_KEY: "partial"' in stream_src
    fallback_src = inspect.getsource(planner.create_plan_with_llm)
    assert 'PLAN_STATUS_KEY] = "partial"' in fallback_src
    fill_src = inspect.getsource(planner._attach_boards_to_authored_plan)
    assert 'PLAN_STATUS_KEY] = "complete"' in fill_src
