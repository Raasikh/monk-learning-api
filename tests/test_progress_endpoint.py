"""/progress assembles a response end to end.

This file exists because the endpoint shipped broken and every test passed.
A refactor replaced an inline entitlement block with a call to
`exam_scope.resolve_exam`, and the local `entitlement` the response dict still
referenced went with it — a NameError raised on every single request. Nothing
covered the assembly, so the suite stayed green while /progress returned 500.

Unit-testing the helpers around it was never going to catch that. The cheapest
test that would have is the dumbest one: build the response once and look at
it. Everything below rides on that single call.
"""

from typing import Any, Dict, List

import pytest

from app.routers import progress as prog

CH = "11111111-1111-1111-1111-111111111111"
CH2 = "22222222-2222-2222-2222-222222222222"
CH3 = "33333333-3333-3333-3333-333333333333"
LIVE = "aaaaaaaa-0000-0000-0000-000000000001"
RETIRED = "aaaaaaaa-0000-0000-0000-000000000002"
OFF = "aaaaaaaa-0000-0000-0000-000000000004"


@pytest.fixture
def wired(monkeypatch):
    """Everything /progress reads, stubbed. Two Physics chapters authored out
    of alphabetical order on purpose, and one retired concept."""
    chapters = [
        # 'Waves' sorts before 'Units & Measurements' alphabetically and after
        # it in the book — the exact inversion the student reported.
        {"id": CH2, "name": "Waves", "subject": "physics",
         "class_level": 11, "chapter_order": 14},
        {"id": CH, "name": "Units & Measurements", "subject": "physics",
         "class_level": 11, "chapter_order": 1},
        # Concepts exist, none tagged for this exam — a board-only chapter.
        {"id": CH3, "name": "Linear Programming", "subject": "physics",
         "class_level": 12, "chapter_order": 20},
    ]
    concepts = [
        {"id": OFF, "chapter_id": CH3, "name": "Corner Point Method",
         "display_order": 1, "exams": ["board"], "active": True},
        {"id": LIVE, "chapter_id": CH2, "name": "Beats",
         "display_order": 1, "exams": ["jee"], "active": True},
        {"id": RETIRED, "chapter_id": CH2, "name": "Maxwell's Equations",
         "display_order": 2, "exams": ["jee"], "active": False},
        {"id": "aaaaaaaa-0000-0000-0000-000000000003", "chapter_id": CH,
         "name": "Significant Figures", "display_order": 1,
         "exams": ["jee"], "active": True},
    ]

    def fake_fetch(table: str, _select: str, **_kw) -> List[Dict[str, Any]]:
        return {
            "progress_config": [{"config": {}}],
            "chapters": chapters,
            "concepts": concepts,
            "chapter_exam_weights": [],
        }.get(table, [])

    monkeypatch.setattr(prog, "fetch_all_cached", fake_fetch)
    monkeypatch.setattr(prog, "_user_bundle", lambda _uid: {
        "profile": {"target_exam": "JEE"},
        # The student has mastered the one real concept in Waves outright, and
        # carries a stale row on the retired one.
        "mastery": [
            {"concept_id": LIVE, "mastery": 100.0, "attempts_first": 3,
             "correct_first": 3, "flag_state": "none", "flagged_at": None},
            {"concept_id": RETIRED, "mastery": 100.0, "attempts_first": 1,
             "correct_first": 1, "flag_state": "none", "flagged_at": None},
        ],
        "snapshots": [], "attempts": 4, "doubts": 0,
    })
    return prog.get_progress(user_id="u1")


def test_the_response_is_built_at_all(wired):
    # The regression, exactly: this raised NameError on every request.
    assert wired["exam"] == "jee"
    assert wired["entitlement"] == "jee"
    assert "monk_score" in wired and "subjects" in wired


def test_chapters_come_back_in_book_order(wired):
    physics = next(s for s in wired["subjects"] if s["subject"] == "physics")
    names = [c["name"] for c in physics["chapters"]]
    # Alphabetically this is exactly backwards, which is what shipped: Units &
    # Measurements is NCERT Class 11 chapter 1 and was being listed last.
    assert names == ["Units & Measurements", "Waves"]


def test_a_retired_concept_is_not_listed(wired):
    physics = next(s for s in wired["subjects"] if s["subject"] == "physics")
    waves = next(c for c in physics["chapters"] if c["name"] == "Waves")
    assert [c["name"] for c in waves["concepts"]] == ["Beats"]


def test_a_retired_concept_does_not_dilute_chapter_mastery(wired):
    # The reason the filter matters, and it is the denominator rather than the
    # listing. Chapter mastery is the mean over the chapter's concepts, so a
    # concept that can never be attempted contributes a permanent zero no
    # amount of work can lift. Class 12 Relations and Functions read 38% for a
    # student who had mastered all five of its real concepts, because eight
    # retired duplicates were still being averaged in.
    physics = next(s for s in wired["subjects"] if s["subject"] == "physics")
    waves = next(c for c in physics["chapters"] if c["name"] == "Waves")
    assert waves["mastery"] == 100.0


def test_the_ledger_counts_only_concepts_the_student_can_see(wired):
    # Both stubbed mastery rows are at 100, but one is on a retired concept
    # that appears nowhere in this response. Counting it would report a total
    # the student cannot reconcile against anything on the page.
    assert wired["ledger"]["concepts_mastered"] == 1


def test_an_off_syllabus_chapter_is_not_scored(wired):
    # A chapter whose concepts all exist but none are on the exam being scored
    # must not appear AND must not count. Listing it would be cosmetic; scoring
    # it is not — chapter mastery is 0 with nothing attemptable, and the
    # subject score averages that in as `num += 0 * w` against `den += w`,
    # dragging Physics down by a chapter the student is never examined on and
    # can never lift. Linear Programming did this to Mathematics the moment it
    # was tagged board-only.
    physics = next(s for s in wired["subjects"] if s["subject"] == "physics")
    names = [c["name"] for c in physics["chapters"]]
    assert "Linear Programming" not in names
    # Waves is fully mastered and Units & Measurements untouched, and the
    # subject score is 10 * mean(chapter mastery): 10 * (100 + 0) / 2 = 500.
    # A third chapter permanently stuck at 0 would make it 10 * 100/3 = 333 —
    # a third of the score gone to a chapter that is not on the exam.
    assert physics["score"] == 500
