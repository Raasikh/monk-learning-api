"""SLOT 1: the precomputed widget payload, and the three ways it can be absent.

Slot 1 of the five-slot board resolution order was requested three times and
blocked three times on "the storage does not exist". That was true of the
TABLES and false of the STORAGE: `lesson_plans.plan_json` is `jsonb`
(migrations/0005_drona.sql) and the segment object inside it already carries a
whole authored SVG under `example_diagram_svg`. A payload goes in beside it.

Four failures live here, and three of them are the same shape as every other
defect in this project — a check that PASSES on absent information:

  1. THE GATE WIDENS AT WRITE TIME. A payload stored at plan time is served
     ahead of everything on every future turn of that segment, so a bad one is
     far more expensive than a bad live one. It goes through
     `sanitize_widget_payload` — the SAME gate the live path uses, not a
     second one — and a payload naming a widget the column did not name is not
     stored either.

  2. AN ABSENT PAYLOAD MEANS FOUR DIFFERENT THINGS. Never eligible, asked and
     declined, answered and dropped, or the call itself failed. Those need four
     different reactions and an absent key tells them apart from nothing. So
     every segment the fill touches records a status.

  3. A DECLINE IS STILL A DECLINE. Nothing is stored, the live path is asked
     again — and because latency is free at plan time, the segment falls
     through to tier 3 there rather than ending up with no picture at all.

  4. THE ORDER COLLAPSES. Slot 1 must outrank slot 2, or the whole point of
     resolving by tier rather than by timing is lost.
"""

import json
from pathlib import Path

import pytest

from app.drona import planner
from app.drona.concept_archetypes import ArchetypeVerdict
from app.drona.planner import (
    WIDGET_PRECOMPUTE_STATES,
    WIDGET_PAYLOAD_KEY,
    WIDGET_PRECOMPUTE_KEY,
    _attach_segment_board,
    _attach_widget_payload,
)
from app.drona.tutor import resolve_board_slot
from app.drona.widget_registry import (
    ROUTE_ARCHETYPE_HIGH,
    WIDGET_VERSIONS,
    sanitize_widget_payload,
)

TUTOR_SRC = Path("app/drona/tutor.py").read_text()
PLANNER_SRC = Path("app/drona/planner.py").read_text()

#: The verdict Biology 12 ch12 "Ecosystem" concepts actually carry.
HIGH = ArchetypeVerdict("process_flow", "process_flow", "high", "high -> `process_flow`")
#: A `med` row, an unknown concept and an unreadable table all land here.
NO_WIDGET = ArchetypeVerdict(None, "labelled_figure", "high",
                             "high, but `labelled_figure` is not a registered widget")

CHAP = {"id": "chap-uuid", "name": "Ecosystem", "subject": "biology"}


# ── stubs ───────────────────────────────────────────────────────────────────

class _Res:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})(),
                                       "finish_reason": "stop"})()]
        self.usage = None


class _FakeClient:
    """One canned answer, and a record of what it was asked."""

    def __init__(self, content):
        self._content = content
        self.calls = []

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kw):
        self.calls.append(kw)
        return _Res(self._content)


@pytest.fixture
def stub_llm(monkeypatch):
    def _install(answer):
        client = _FakeClient(answer if isinstance(answer, str) else json.dumps(answer))
        monkeypatch.setattr(planner, "get_drona_client", lambda: client)
        monkeypatch.setattr(planner, "record_call", lambda *a, **k: None)
        return client
    return _install


def _segment(objective="How carbon moves between the atmosphere and biomass"):
    return {
        "id": 1,
        "objective": objective,
        "teaching_notes": "Walk the cycle one reservoir at a time.",
        "board_content": ["Carbon cycle", "Photosynthesis fixes CO2"],
        "checkpoint": {"question": "q", "model_answer": "a", "rubric": "r",
                       "expected_misconceptions": ["m1", "m2"]},
    }


GOOD_PAYLOAD = {"widget": "process_flow", "version": 1,
                "params": {"nodes": ["Atmosphere", "Producers", "Decomposers"],
                           "layout": "ring"}}


# ── 1. a high-confidence concept stores a payload ───────────────────────────

def test_a_high_confidence_concept_stores_a_payload(stub_llm):
    """Path 1 of docs/widget-routing.md, precomputed. The column named
    `process_flow`, the model filled its params, the gate passed."""
    stub_llm({"payload": GOOD_PAYLOAD, "caption": "the carbon cycle"})
    seg = _segment()

    status = _attach_widget_payload(seg, HIGH, CHAP, "Carbon Cycle",
                                    subtopic_key="carbon-cycle")

    assert status == "stored"
    assert seg[WIDGET_PAYLOAD_KEY] == GOOD_PAYLOAD
    rec = seg[WIDGET_PRECOMPUTE_KEY]
    assert rec["status"] == "stored"
    assert rec["widget"] == "process_flow"
    assert rec["route"] == ROUTE_ARCHETYPE_HIGH
    # Provenance travels with it, computed from the CSV's own bytes.
    assert rec["archetype_version"] and rec["archetype_version"] != "unreadable"


def test_the_ask_reuses_the_live_paths_single_widget_block(stub_llm):
    """Not a second copy of the widget's schema in a different voice. The
    live path's block is the one that ships, so the params asked for at plan
    time and the params asked for live are the same text."""
    from app.drona.widget_registry import render_single_widget_block

    client = stub_llm({"payload": GOOD_PAYLOAD})
    _attach_widget_payload(_segment(), HIGH, CHAP, "Carbon Cycle")

    system = client.calls[0]["messages"][0]["content"]
    assert render_single_widget_block("process_flow") in system
    # and the block refers to "[CURRENT SEGMENT] below", so that heading has to
    # exist or its own instruction points at nothing.
    assert "[CURRENT SEGMENT]" in client.calls[0]["messages"][1]["content"]


def test_a_concept_the_column_never_named_is_not_asked_and_says_so(stub_llm):
    """`not_asked` is NOT `declined`, and that is the whole reason the status
    is written on every segment rather than only on the ones that fired."""
    client = stub_llm({"payload": GOOD_PAYLOAD})
    seg = _segment()

    status = _attach_widget_payload(seg, NO_WIDGET, CHAP, "Ecological Succession")

    assert status == "not_asked"
    assert WIDGET_PAYLOAD_KEY not in seg
    assert seg[WIDGET_PRECOMPUTE_KEY]["status"] == "not_asked"
    assert seg[WIDGET_PRECOMPUTE_KEY]["widget"] is None
    # and nothing was billed for a question nobody asked
    assert client.calls == []


# ── 2. a decline stores nothing, and falls to tier 3 ────────────────────────

def test_a_decline_stores_nothing_and_is_recorded_as_a_decline(stub_llm):
    stub_llm({"decline": "this segment is a definition; there is nothing to walk"})
    seg = _segment()

    status = _attach_widget_payload(seg, HIGH, CHAP, "Carbon Cycle")

    assert status == "declined"
    assert WIDGET_PAYLOAD_KEY not in seg
    rec = seg[WIDGET_PRECOMPUTE_KEY]
    assert rec["status"] == "declined"
    # The volunteered reason is kept. It is the only signal for where the
    # archetype column is too coarse for a segment.
    assert "definition" in rec["why"]


def test_an_answer_with_no_payload_and_no_reason_is_still_a_decline(stub_llm):
    """v4 asked for the decline out loud and got zero in 40 turns. An absent
    payload on a turn that WAS asked is a judgement, not an absence."""
    stub_llm({})
    seg = _segment()
    assert _attach_widget_payload(seg, HIGH, CHAP, "Carbon Cycle") == "declined"
    assert WIDGET_PAYLOAD_KEY not in seg


def test_a_precompute_decline_falls_through_to_tier_three(monkeypatch, stub_llm):
    """The product owner's ruling: in PRECOMPUTE a decline falls to tier 3; in
    LIVE a decline shows no picture. Latency is free here, so a declined
    segment gets an authored SVG rather than nothing — and because slot 4 sits
    BELOW slot 2, that SVG cannot stop the live path being asked again."""
    stub_llm({"decline": "nothing to draw"})
    drawn = []

    def _fake_author(**kw):
        drawn.append(kw)
        return "<svg/>", "ok"

    import app.drona.diagram_author as da
    monkeypatch.setattr(da, "author_diagram", _fake_author)

    # An objective with NO worked-example cue: `_attach_example_diagram` would
    # return early on its own, so an SVG here can only come from `force=True`.
    seg = _segment(objective="Define the trophic levels of an ecosystem")
    status = _attach_segment_board(seg, CHAP, "Energy Flow", HIGH)

    assert status == "declined"
    assert seg.get("example_diagram_svg") == "<svg/>"
    assert len(drawn) == 1


def test_a_stored_payload_does_not_force_a_tier_three_svg(monkeypatch, stub_llm):
    """The forced fallthrough is for declines only. A segment that already has
    the highest tier does not also pay for the lowest."""
    stub_llm({"payload": GOOD_PAYLOAD})
    drawn = []
    import app.drona.diagram_author as da
    monkeypatch.setattr(da, "author_diagram",
                        lambda **kw: (drawn.append(kw), ("<svg/>", "ok"))[1])

    seg = _segment(objective="Define the trophic levels of an ecosystem")
    assert _attach_segment_board(seg, CHAP, "Energy Flow", HIGH) == "stored"
    assert "example_diagram_svg" not in seg
    assert drawn == []


# ── 3. slot 1 outranks slot 2 ───────────────────────────────────────────────

def test_slot_one_outranks_slot_two_when_both_could_fire(stub_llm):
    """Both CAN fire on the same segment by construction — slot 1's read
    requires the stored widget to be the one the column names right now, so
    every filled slot 1 is a segment where slot 2 would also have fired. If
    the order were wrong, the precompute would be dead weight and every turn
    would pay for params it already had."""
    assert resolve_board_slot(precomputed_widget=GOOD_PAYLOAD,
                              archetype_widget="process_flow") == "widget_precomputed"
    # and it still outranks the two slots below it
    assert resolve_board_slot(precomputed_widget=GOOD_PAYLOAD,
                              archetype_widget="process_flow",
                              illustration_asset="x",
                              precomputed_svg="<svg/>") == "widget_precomputed"


def test_the_slot_one_branch_runs_before_the_archetype_branch():
    """The resolver having the right order decides nothing on its own: the
    branch that runs FIRST is what the model is actually asked for."""
    pre = TUTOR_SRC.index('if _board_slot == "widget_precomputed":')
    arch = TUTOR_SRC.index("elif _archetype_widget:")
    assert pre < arch


def test_slot_one_delivery_is_unconditional_and_slot_four_is_not():
    """THE DIFFERENCE BETWEEN A TIER AND A FALLBACK. Slot 4 appends only when
    the turn drew nothing — correct, because a cached tier-3 SVG must never
    outrank the slots above it. Slot 1 is the top tier: it appends whatever the
    turn did, and a stray model diagram loses to it."""
    body = TUTOR_SRC[TUTOR_SRC.index("SLOT 1 delivery"):]
    slot1 = body[:body.index("SLOT 4 delivery")]
    assert "if _precomputed_widget:" in slot1
    assert "not any(" not in slot1, "slot 1 was written as a fallback, not a tier"
    assert "SLOT 1 OUTRANKS" in slot1
    # slot 4 keeps its guard
    slot4 = body[body.index("SLOT 4 delivery"):]
    assert "if _precomputed_svg and not any(" in slot4


def test_a_slot_one_turn_is_not_counted_as_a_widget_decline():
    """On a slot-1 turn the model is told the picture exists and NOT to emit
    one. Counting the absent payload as a decline would manufacture the exact
    signal the decline log exists to measure."""
    idx = TUTOR_SRC.index("_decline = classify_widget_decline(")
    block = TUTOR_SRC[idx:idx + 200]
    assert '_board_slot == "widget_archetype"' in block


# ── 4. a payload that fails the gate is not stored ──────────────────────────

@pytest.mark.parametrize("bad,why", [
    ({"widget": "not_a_widget", "version": 1, "params": {"a": 1}}, "unknown id"),
    ({"widget": "process_flow", "version": 99, "params": {"a": 1}}, "version newer than shipped"),
    ({"widget": "process_flow", "version": 1, "params": {}}, "empty params"),
    ({"widget": "process_flow", "version": 1}, "no params at all"),
    ("not an object", "payload is not an object"),
])
def test_a_payload_that_fails_the_gate_is_not_stored(stub_llm, bad, why):
    stub_llm({"payload": bad})
    seg = _segment()

    status = _attach_widget_payload(seg, HIGH, CHAP, "Carbon Cycle")

    assert status == "rejected", why
    assert WIDGET_PAYLOAD_KEY not in seg
    assert seg[WIDGET_PRECOMPUTE_KEY]["status"] == "rejected"


def test_the_write_uses_the_same_gate_as_the_live_path_not_a_second_one():
    """Two validators that can disagree is worse than one coarse one, and the
    first time they disagreed this side would be the wrong one."""
    block = PLANNER_SRC[PLANNER_SRC.index("def _attach_widget_payload("):]
    block = block[:block.index("\ndef ")]
    assert "sanitize_widget_payload(raw_payload, archetype_widget=widget_id)" in block
    # no home-grown params checking beside it
    assert "isinstance(params" not in block


def test_a_payload_naming_a_different_widget_is_not_stored(stub_llm):
    """LIVE, a model that ignores the named widget still emitted something the
    client can draw, so it is kept as `model_choice` rather than dropped for
    carrying the wrong label. STORED, it is different: it would become a
    permanent cached picture that no classification chose, served ahead of the
    live path on every future turn of that segment. Slot 1 stores only what
    path 1 actually produced."""
    off = {"widget": "xy_plot", "version": 1, "params": {"curve": [[0, 0], [1, 1]]}}
    # it passes the gate — this is not a gate question
    assert sanitize_widget_payload(off, archetype_widget="process_flow") is not None
    stub_llm({"payload": off})
    seg = _segment()

    assert _attach_widget_payload(seg, HIGH, CHAP, "Carbon Cycle") == "rejected"
    assert WIDGET_PAYLOAD_KEY not in seg
    assert "xy_plot" in seg[WIDGET_PRECOMPUTE_KEY]["why"]


def test_a_call_that_failed_is_an_error_not_a_decline(monkeypatch):
    """Nobody judged anything. Booking it as a decline would put a model
    opinion in the record where a network failure happened."""
    class _Boom:
        @property
        def chat(self): return self
        @property
        def completions(self): return self
        def create(self, **kw): raise RuntimeError("gateway 503")

    monkeypatch.setattr(planner, "get_drona_client", lambda: _Boom())
    monkeypatch.setattr(planner, "record_call", lambda *a, **k: None)
    seg = _segment()

    assert _attach_widget_payload(seg, HIGH, CHAP, "Carbon Cycle") == "error"
    assert WIDGET_PAYLOAD_KEY not in seg
    assert seg[WIDGET_PRECOMPUTE_KEY]["status"] == "error"


# ── the read side re-gates what the write side stored ───────────────────────

def test_the_stored_payload_is_re_gated_on_read():
    """Written by an earlier process against an earlier registry. A payload the
    CLIENT can no longer resolve fails SILENTLY on device: `lookup()` returns
    null and the board draws nothing at all."""
    body = TUTOR_SRC[TUTOR_SRC.index("── SLOT 1"):TUTOR_SRC.index("── SLOT 2:")]
    assert "sanitize_widget_payload(_stored_widget" in body
    assert 'ROUTE_ARCHETYPE_HIGH' in body
    assert "rejected on read" in body


def test_the_read_gate_refuses_a_payload_the_column_no_longer_names():
    """A reclassification that moved the concept, or a CSV that cannot be read
    at all, must EMPTY slot 1 rather than serve a cached picture no live
    classification chose. `table_unreadable` yields no archetype widget, so
    this is also what an unreadable table does."""
    gated = sanitize_widget_payload(GOOD_PAYLOAD, archetype_widget=None)
    assert gated is not None                       # the client could still draw it
    assert gated["route"] != ROUTE_ARCHETYPE_HIGH  # but slot 1 will not serve it


def test_slot_one_needed_no_migration_and_the_code_says_why():
    """Three attempts stopped on 'the storage does not exist'. The note that
    it was true of the tables and false of the storage has to survive."""
    assert "jsonb" in PLANNER_SRC[PLANNER_SRC.index("SLOT 1 of the board resolution order"):
                                  PLANNER_SRC.index("WIDGET_PAYLOAD_KEY")]
    assert WIDGET_VERSIONS.get("process_flow") == 1


# ── what the first Ecosystem run found: an ABSENCE wearing an ANSWER's clothes ──
#
# The first live run lost concept 1 of 10 entirely. One transient "Server
# disconnected" from the shared PostgREST client, raised on the detached fill
# thread while the poller was hitting the same client, produced
# `confidence == "lookup_error"` — and then TWO separate mechanisms turned that
# blip into a permanent, silent, plausible-looking "this concept has no
# widget". Neither failed anything. The run printed COMPLETE.

def test_a_transient_lookup_error_is_not_cached_as_a_verdict():
    """`_SESSION_CACHE` memoises per process, so a socket error cached once was
    the answer for that concept until the process died. A concept's name does
    not change under a running server; a socket does."""
    from app.drona import concept_archetypes as ca

    ca._SESSION_CACHE.clear()
    calls = []

    class _Boom:
        def table(self, *a, **k):
            calls.append(1)
            raise RuntimeError("Server disconnected")

    import app.db
    real = app.db.supabase
    try:
        app.db.supabase = _Boom()
        first = ca.concept_archetype_for_session("chap", "carbon-cycle")
        assert first.confidence == "lookup_error"
        assert "carbon-cycle" not in " ".join(ca._SESSION_CACHE)
        ca.concept_archetype_for_session("chap", "carbon-cycle")
        assert len(calls) == 2, "the failed lookup was cached and never retried"
    finally:
        app.db.supabase = real
        ca._SESSION_CACHE.clear()


def test_an_unreadable_column_is_unresolved_not_not_asked():
    """"The column says no widget" and "the column could not be read" are
    different facts with different owners, and only the first is an answer.
    Recorded as one status they are indistinguishable in the plan — which is
    exactly how a whole concept's eight segments came back looking like an
    ordinary non-widget concept."""
    from app.drona.concept_archetypes import ArchetypeVerdict

    for conf in ("lookup_error", "table_unreadable", "unjoinable"):
        seg = _segment()
        v = ArchetypeVerdict(None, "", conf, f"{conf} happened")
        assert _attach_widget_payload(seg, v, CHAP, "Carbon Cycle") == "unresolved"
        assert seg[WIDGET_PRECOMPUTE_KEY]["archetype_confidence"] == conf

    # and an actual verdict of "no widget" is still `not_asked`
    seg = _segment()
    assert _attach_widget_payload(seg, NO_WIDGET, CHAP, "Carbon Cycle") == "not_asked"


def test_every_status_the_code_can_produce_is_a_declared_one():
    """A status the tally does not know about is a segment nobody counts."""
    assert set(WIDGET_PRECOMPUTE_STATES) == {
        "not_asked", "unresolved", "stored", "declined", "rejected", "error"}


def test_an_unresolved_archetype_does_not_burn_a_tier_three_call(monkeypatch, stub_llm):
    """A decline is a judgement worth paying to work around. A socket error is
    not — the plan regenerates and the live path resolves the column per turn,
    so paying a diagram_author call per segment for a blip is paying for a
    failure."""
    from app.drona.concept_archetypes import ArchetypeVerdict

    drawn = []
    import app.drona.diagram_author as da
    monkeypatch.setattr(da, "author_diagram",
                        lambda **kw: (drawn.append(kw), ("<svg/>", "ok"))[1])
    stub_llm({"payload": GOOD_PAYLOAD})

    seg = _segment(objective="Define the trophic levels of an ecosystem")
    v = ArchetypeVerdict(None, "", "lookup_error", "Server disconnected")
    assert _attach_segment_board(seg, CHAP, "Energy Flow", v) == "unresolved"
    assert drawn == []


def test_the_archetype_is_resolved_off_the_detached_fill_thread():
    """The fill runs detached beside a poller on the SAME shared PostgREST
    client, which is where the disconnect was raised. The verdict is read on
    the main thread and handed in; the in-thread read stays only as a fallback
    for direct callers."""
    body = PLANNER_SRC[PLANNER_SRC.index("def create_plan_streaming("):]
    body = body[:body.index("def get_or_create_plan(")]
    assert "archetype = concept_archetype_for_session(chapter_id, subtopic_key)" in body
    assert "subtopic_key, archetype)" in body
    fill = PLANNER_SRC[PLANNER_SRC.index("def _fill_remaining_segments("):]
    assert "if archetype is None:" in fill[:4000]


def test_an_unresolved_archetype_is_logged_loudly_not_quietly():
    """With no verdict every concept looks like a concept with no widget and
    slot 1 is silently empty on a run that reports itself complete."""
    fill = PLANNER_SRC[PLANNER_SRC.index("def _fill_remaining_segments("):]
    block = fill[:fill.index("try:")]
    assert "logger.warning if _unresolved else logger.info" in block
    assert "UNRESOLVED" in block
