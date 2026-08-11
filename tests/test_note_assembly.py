"""Tests for the note assembler (app/drona/note_assembly.py).

The rule these protect: a note contains what the student actually saw, and
nothing else. A session abandoned in segment 2 of 9 must not save nine segments
of board, and a session where the board never got written must refuse to save
rather than produce an empty note.

These are unit tests over the assembler with the database stubbed. They do NOT
prove the HTTP path works — scratch/e2e_notes_and_doubts.py does that.

Runs under pytest, or standalone:  python3 tests/test_note_assembly.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import app.drona.note_assembly as na  # noqa: E402
from app.drona.note_assembly import NoteAssemblyError, assemble_session_note  # noqa: E402


# --- stub Supabase ----------------------------------------------------------

def _board(seg_no: int, count: int):
    """A segment's authored board: one heading then text items."""
    return [
        {"seq": i, "type": "heading" if i == 1 else "text",
         "text": f"S{seg_no} item {i}", "emphasis": "normal"}
        for i in range(1, count + 1)
    ]


def make_plan(segment_count: int = 9, items_per_segment: int = 6):
    return {
        "topic": "Projectile Motion",
        "segments": [
            {"id": i, "title": f"Segment {i}", "objective": f"Objective {i}",
             "board_content": _board(i, items_per_segment)}
            for i in range(1, segment_count + 1)
        ],
        "wrapup_points": [f"Point {i}" for i in range(1, segment_count + 1)],
    }


def make_turns(spec):
    """spec: list of (segment_index, [seq numbers emitted this turn])."""
    return [
        {
            "segment_index": seg,
            "board_event_count": len(seqs),
            "raw_response": json.dumps({
                "board_events": [{"seq": s, "type": "text", "text": f"e{s}"} for s in seqs]
            }),
        }
        for seg, seqs in spec
    ]


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return type("Res", (), {"data": self._rows})()


def install_stub(monkeypatch, *, session, plan, turns, chapter=None):
    tables = {
        "drona_sessions": [session] if session else [],
        "lesson_plans": [{"plan_json": plan}] if plan is not None else [],
        "drona_turns": turns,
        "chapters": [chapter] if chapter else [],
    }

    class _Supabase:
        def table(self, name):
            return _Query(tables.get(name, []))

    monkeypatch.setattr(na, "supabase", _Supabase())


SESSION = {
    "id": "sess-1", "user_id": "user-1", "chapter_id": "chap-1",
    "subtopic_key": "projectile-motion", "plan_id": "plan-1",
    "phase": "complete", "current_segment": 2, "segments_completed": 1,
    "language": "english", "created_at": "2026-08-10T19:08:22Z",
}
CHAPTER = {"name": "Motion in a Plane", "subject": "physics", "class_level": 11}


# --- what the student saw is what gets saved --------------------------------

def test_only_reached_segments_are_saved(monkeypatch):
    """Stopped in segment 2 of 9 -> the note holds 2 segments, not 9."""
    install_stub(
        monkeypatch,
        session={**SESSION, "segments_completed": 1, "current_segment": 2},
        plan=make_plan(9, 6),
        turns=make_turns([(1, [1, 2, 3]), (1, [4, 5, 6]), (2, [1, 2])]),
        chapter=CHAPTER,
    )
    note = assemble_session_note("sess-1", "user-1")
    print(f"  segments_covered={note['segments_covered']} of {note['total_segments']}")
    assert note["segments_covered"] == 2
    assert note["total_segments"] == 9


def test_full_lesson_kept_with_covered_boundary(monkeypatch):
    """Policy ca883b8: the note holds every segment; `covered` marks the line.

    A student who stopped in segment 2 of 9 still gets the whole lesson as
    revision notes — but covered/uncovered stay distinguishable.
    """
    install_stub(
        monkeypatch,
        session={**SESSION, "segments_completed": 1, "current_segment": 2},
        plan=make_plan(9, 6),
        turns=make_turns([(1, [1, 2, 3]), (1, [4, 5, 6]), (2, [1, 2])]),
        chapter=CHAPTER,
    )
    note = assemble_session_note("sess-1", "user-1")
    flags = [(g["segment_index"], g["covered"]) for g in note["board_items"]]
    print(f"  covered flags: {flags}")
    assert len(note["board_items"]) == 9
    assert [f for _, f in flags] == [True, True] + [False] * 7
    assert note["item_count"] == 9 * 6



def test_every_segment_keeps_its_whole_board(monkeypatch):
    install_stub(
        monkeypatch,
        session={**SESSION, "segments_completed": 3, "current_segment": 4},
        plan=make_plan(9, 7),
        turns=make_turns([(1, [1, 2, 3]), (2, [1, 2]), (3, [1]), (4, [1, 2, 3])]),
        chapter=CHAPTER,
    )
    note = assemble_session_note("sess-1", "user-1")
    sizes = {g["segment_index"]: len(g["items"]) for g in note["board_items"]}
    print(f"  sizes={sizes} covered={note['segments_covered']}")
    assert all(size == 7 for size in sizes.values())
    assert note["segments_covered"] == 4



def test_turns_extend_the_covered_boundary(monkeypatch):
    """Ended mid-segment: segments_completed says 1, the turn log says 2."""
    install_stub(
        monkeypatch,
        session={**SESSION, "segments_completed": 1, "current_segment": 2},
        plan=make_plan(6, 6),
        turns=make_turns([(1, [1, 2, 3, 4, 5, 6]), (2, [1, 2, 3])]),
        chapter=CHAPTER,
    )
    note = assemble_session_note("sess-1", "user-1")
    print(f"  segments_covered={note['segments_covered']} of {note['total_segments']}")
    assert note["segments_covered"] == 2



def test_seqless_turns_still_mark_coverage(monkeypatch):
    """Older turns with no seq numbers still count toward the boundary."""
    turns = [
        {"segment_index": 1, "board_event_count": 3, "raw_response": json.dumps({"board_events": []})},
        {"segment_index": 1, "board_event_count": 2, "raw_response": json.dumps({"board_events": []})},
    ]
    install_stub(
        monkeypatch,
        session={**SESSION, "segments_completed": 0, "current_segment": 1},
        plan=make_plan(6, 6),
        turns=turns,
        chapter=CHAPTER,
    )
    note = assemble_session_note("sess-1", "user-1")
    print(f"  segments_covered={note['segments_covered']}")
    assert note["segments_covered"] == 1



def test_malformed_raw_response_does_not_lose_the_note(monkeypatch):
    """One unparseable turn must not sink the save."""
    turns = [
        {"segment_index": 1, "board_event_count": 3, "raw_response": "{not json"},
        {"segment_index": 1, "board_event_count": 3,
         "raw_response": json.dumps({"board_events": [{"seq": 4}, {"seq": 5}, {"seq": 6}]})},
    ]
    install_stub(
        monkeypatch,
        session={**SESSION, "segments_completed": 0, "current_segment": 1},
        plan=make_plan(6, 6),
        turns=turns,
        chapter=CHAPTER,
    )
    note = assemble_session_note("sess-1", "user-1")
    print(f"  saved with covered={note['segments_covered']}")
    assert note["segments_covered"] == 1



# --- refusals: never save an empty or invented note -------------------------

def test_zero_turn_session_saves_the_full_lesson_uncovered(monkeypatch):
    """Policy ca883b8 inverts the old refusal: a session that never reached the
    board still saves — the full lesson, with nothing marked covered."""
    install_stub(
        monkeypatch,
        session={**SESSION, "segments_completed": 0, "current_segment": 1},
        plan=make_plan(6, 6),
        turns=[],
        chapter=CHAPTER,
    )
    note = assemble_session_note("sess-1", "user-1")
    print(f"  covered={note['segments_covered']}, items={note['item_count']}")
    assert note["segments_covered"] == 0
    assert note["item_count"] == 36



def test_session_without_a_plan_refuses(monkeypatch):
    install_stub(
        monkeypatch,
        session={**SESSION, "plan_id": None},
        plan=None,
        turns=[],
    )
    with pytest.raises(NoteAssemblyError) as err:
        assemble_session_note("sess-1", "user-1")
    print(f"  refused: {err.value}")


def test_missing_plan_row_refuses(monkeypatch):
    install_stub(monkeypatch, session=SESSION, plan=None, turns=[])
    with pytest.raises(NoteAssemblyError) as err:
        assemble_session_note("sess-1", "user-1")
    print(f"  refused: {err.value}")


def test_another_users_session_is_not_found(monkeypatch):
    """Ownership is filtered in the query; no rows come back."""
    install_stub(monkeypatch, session=None, plan=make_plan(), turns=[])
    with pytest.raises(NoteAssemblyError) as err:
        assemble_session_note("sess-1", "someone-else")
    print(f"  refused: {err.value}")


# --- metadata ---------------------------------------------------------------

def test_note_carries_chapter_and_topic_metadata(monkeypatch):
    """Keys must match the `notes` columns the web pages read."""
    install_stub(
        monkeypatch,
        session=SESSION,
        plan=make_plan(9, 6),
        turns=make_turns([(1, [1, 2, 3, 4, 5, 6])]),
        chapter=CHAPTER,
    )
    note = assemble_session_note("sess-1", "user-1")
    print(f"  concept={note['concept']!r} subject={note['subject']!r} "
          f"chapter={note['chapter']!r}")
    assert note["concept"] == "Projectile Motion"
    assert note["subject"] == "Physics"
    assert note["chapter"] == "Motion in a Plane"


def test_note_keys_match_the_notes_table(monkeypatch):
    """Guards against drift: every key must be a real column on `notes`."""
    install_stub(
        monkeypatch,
        session=SESSION,
        plan=make_plan(9, 6),
        turns=make_turns([(1, [1, 2, 3, 4, 5, 6])]),
        chapter=CHAPTER,
    )
    note = assemble_session_note("sess-1", "user-1")
    columns = {
        "user_id", "session_id", "chapter_id", "subject", "chapter", "concept",
        "content", "board_items", "segments_covered", "total_segments",
        "item_count", "session_started_at",
    }
    extra = set(note) - columns
    print(f"  keys={sorted(note)}")
    print(f"  not columns on `notes`: {extra or 'none'}")
    assert not extra


def test_content_is_readable_text(monkeypatch):
    """`notes.content` is rendered as a plain string by the note page."""
    install_stub(
        monkeypatch,
        session=SESSION,
        plan=make_plan(9, 6),
        turns=make_turns([(1, [1, 2, 3, 4, 5, 6])]),
        chapter=CHAPTER,
    )
    note = assemble_session_note("sess-1", "user-1")
    print(f"  content[:60]={note['content'][:60]!r}")
    assert isinstance(note["content"], str)
    assert "Segment 1" in note["content"]
    assert "S1 item 2" in note["content"]


def test_plan_json_arriving_as_a_string_is_parsed(monkeypatch):
    """plan_json is jsonb but some writers store it as a JSON string."""
    install_stub(
        monkeypatch,
        session=SESSION,
        plan=json.dumps(make_plan(6, 6)),
        turns=make_turns([(1, [1, 2, 3, 4, 5, 6])]),
        chapter=CHAPTER,
    )
    note = assemble_session_note("sess-1", "user-1")
    print(f"  parsed string plan_json -> {note['item_count']} items (full lesson)")
    assert note["item_count"] == 36
