"""A student is served the syllabus they paid for, and no other.

The Learn catalogue served the entire corpus to everyone until this module
existed: a NEET student was offered all 27 Mathematics chapters — not on their
syllabus at any point in the exam — alongside every JEE-only concept inside the
physics and chemistry chapters the two exams do share. The `exams` tag that
should have prevented it was already present on all 1,144 concept rows. Nothing
read it.

Progress had the entitlement logic right the whole time, inline. Duplicating it
by hand into the catalogue is how the two would have drifted, so both now call
this module and these tests pin the behaviour that matters.
"""

import pytest

from app.exam_scope import (
    SUBJECTS_BY_EXAM,
    allowed_exams,
    entitlement_of,
    resolve_exam,
    selected_exam,
    subject_on_syllabus,
    subjects_for,
    tagged_for_exam,
)


# ── Entitlement ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("JEE", "jee"),
    ("NEET", "neet"),
    ("both", "both"),
    ("jee", "jee"),
    ("  NeEt  ", "neet"),          # written by onboarding, casing not guaranteed
    ("JEE + NEET both", "both"),
])
def test_entitlement_is_read_case_and_space_insensitively(raw, expected):
    assert entitlement_of({"target_exam": raw}) == expected


@pytest.mark.parametrize("profile", [None, {}, {"target_exam": None}, {"target_exam": ""}])
def test_unknown_entitlement_falls_back_to_the_shared_syllabus(profile):
    # A profile that cannot be read must not produce an empty catalogue: a
    # blank Learn page looks like missing content and sends you hunting through
    # the corpus, whereas the wrong-but-populated default is visible at a
    # glance. Matches what Progress has always done.
    assert entitlement_of(profile) == "jee"


# ── Entitlement is not a preference ──────────────────────────────────────────

def test_a_neet_student_cannot_request_the_jee_view():
    # This is the property that makes it an entitlement check rather than a
    # filter: ?exam= is honoured only within what the student is entitled to.
    assert resolve_exam({"target_exam": "NEET"}, "jee") == "neet"
    assert resolve_exam({"target_exam": "JEE"}, "neet") == "jee"


def test_a_both_student_may_switch_views():
    assert resolve_exam({"target_exam": "both"}, "neet") == "neet"
    assert resolve_exam({"target_exam": "both"}, "jee") == "jee"
    assert allowed_exams("both") == ("jee", "neet")


def test_a_junk_exam_param_falls_back_rather_than_erroring():
    assert resolve_exam({"target_exam": "both"}, "physics") == "jee"
    assert resolve_exam({"target_exam": "NEET"}, None) == "neet"


# ── Subjects ─────────────────────────────────────────────────────────────────

def test_maths_is_jee_only_and_biology_is_neet_only():
    # The 27 Mathematics chapters and 32 Biology chapters are the bulk of what
    # was being wrongly offered, so these two are the load-bearing assertions.
    assert subject_on_syllabus("mathematics", "jee")
    assert not subject_on_syllabus("mathematics", "neet")
    assert subject_on_syllabus("biology", "neet")
    assert not subject_on_syllabus("biology", "jee")


def test_physics_and_chemistry_are_shared():
    for subject in ("physics", "chemistry"):
        assert subject_on_syllabus(subject, "jee")
        assert subject_on_syllabus(subject, "neet")


def test_subject_matching_survives_the_casing_in_the_chapters_table():
    assert subject_on_syllabus("Physics", "jee")
    assert subject_on_syllabus("  BIOLOGY ", "neet")
    assert not subject_on_syllabus(None, "jee")


def test_both_sees_the_union():
    assert set(subjects_for("both")) == {"physics", "chemistry", "mathematics", "biology"}
    for exam in ("jee", "neet"):
        assert set(subjects_for(exam)) == set(SUBJECTS_BY_EXAM[exam])


# ── Concept tags ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tags,exam,expected", [
    (["jee", "neet"], "jee", True),
    (["jee", "neet"], "neet", True),
    (["jee"], "neet", False),
    (["neet"], "jee", False),
    (["JEE"], "jee", True),          # tags are lowercase today; do not depend on it
    ("neet", "neet", True),          # a bare string, not a list
    (["jee"], "both", True),
])
def test_concept_tags_gate_by_exam(tags, exam, expected):
    assert tagged_for_exam(tags, exam) is expected


@pytest.mark.parametrize("tags", [None, [], ""])
def test_untagged_concepts_are_shared_not_hidden(tags):
    # All 1,144 concepts are tagged today, so this is unreachable now. It is
    # pinned because the two failure modes are not equally recoverable: a
    # concept shown to the wrong exam is visible and gets reported, while one
    # silently hidden is indistinguishable from a chapter nobody authored.
    assert tagged_for_exam(tags, "jee") is True
    assert tagged_for_exam(tags, "neet") is True


# ── Selection: what the Learn catalogue asks ─────────────────────────────────
# Progress asks about an entitlement; Learn asks about a pick. The defaults are
# opposites and that is the whole point, so both are pinned.

@pytest.mark.parametrize("requested", [None, "", "   ", "both", "physics", "JEE+NEET"])
def test_the_catalogue_hides_nothing_until_a_student_picks(requested):
    # Anything that is not a clean 'jee' or 'neet' means "no pick yet". Hiding
    # content on a junk or absent param would make a broken chapter and a
    # filtered-out chapter indistinguishable from the outside.
    assert selected_exam(requested) == "both"


@pytest.mark.parametrize("requested,expected", [
    ("jee", "jee"), ("neet", "neet"), ("JEE", "jee"), ("  NeEt ", "neet"),
])
def test_an_explicit_pick_narrows(requested, expected):
    assert selected_exam(requested) == expected


def test_selection_and_entitlement_default_in_opposite_directions():
    # The Learn catalogue opens up when it knows nothing; Progress falls back
    # to a concrete exam because a score has to be computed against one. Wiring
    # either surface to the other's resolver silently changes what a student
    # sees, so this pins the two apart.
    assert selected_exam(None) == "both"
    assert resolve_exam(None, None) == "jee"


def test_both_passes_every_concept_and_subject():
    # 'both' must be a true no-op, not a third syllabus: this is the mode the
    # catalogue runs in by default today.
    for subject in ("physics", "chemistry", "mathematics", "biology"):
        assert subject_on_syllabus(subject, "both")
    for tags in (["jee"], ["neet"], ["jee", "neet"], None):
        assert tagged_for_exam(tags, "both") is True
