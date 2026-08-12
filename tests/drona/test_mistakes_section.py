"""The rework section quotes the student's own graded answers into the note.

Deterministic by design: questions, answers and corrections are lifted from
the turn rows verbatim, never paraphrased by a model call.
"""
import json

from app.drona.note_assembly import (
    CLASS_END_MARKER,
    MISTAKES_HEADING,
    SELF_STUDY_HEADING,
    mistakes_section_from_turns,
    weave_mistakes_into_content,
)


def _turn(idx, phase_in, utterance="", grade=None, speech=""):
    return {
        "turn_index": idx,
        "phase_in": phase_in,
        "utterance": utterance,
        "grade": grade,
        "raw_response": json.dumps({"speech": speech}),
    }


ASKING_TURN = _turn(
    1, "teaching", "Begin lesson segment",
    speech="Gravity pulls it down. Now, if you double the height, what happens to the fall time?",
)


def test_no_graded_turns_yields_no_section():
    assert mistakes_section_from_turns([ASKING_TURN]) is None


def test_all_correct_yields_no_section():
    turns = [
        ASKING_TURN,
        _turn(2, "awaiting_answer", "It increases by root two", "correct",
              speech="That's very good! Let's move on."),
    ]
    assert mistakes_section_from_turns(turns) is None


def test_incorrect_answer_is_quoted_with_question_and_correction():
    turns = [
        ASKING_TURN,
        _turn(2, "awaiting_answer", "It doubles", "incorrect",
              speech="That's not quite right. The time grows by a factor of root two, not two. Now let's look at range."),
    ]
    section = mistakes_section_from_turns(turns)
    assert section.startswith(MISTAKES_HEADING)
    assert "Checkpoint 1:" in section
    assert "• Asked: Now, if you double the height, what happens to the fall time?" in section
    assert "• You said: It doubles" in section
    # Correction is the first two sentences only — the transition line stays out.
    assert "factor of root two" in section
    assert "Now let's look at range" not in section


def test_partial_grade_is_labelled():
    turns = [
        ASKING_TURN,
        _turn(2, "awaiting_answer", "It increases", "partial",
              speech="Partly right — it increases, but specifically by root two."),
    ]
    section = mistakes_section_from_turns(turns)
    assert "• You said: It increases (partly right)" in section


def test_correct_answers_are_counted_in_closing_line():
    turns = [
        ASKING_TURN,
        _turn(2, "awaiting_answer", "It doubles", "incorrect", speech="Not quite. It grows by root two."),
        _turn(3, "teaching", speech="Next idea. Which channel has constant velocity?"),
        _turn(4, "awaiting_answer", "Horizontal", "correct", speech="That's very good."),
    ]
    section = mistakes_section_from_turns(turns)
    assert "• You answered 1 other checkpoint correctly." in section


def test_empty_utterance_is_skipped():
    turns = [
        ASKING_TURN,
        _turn(2, "awaiting_answer", "   ", "incorrect", speech="Not quite."),
    ]
    assert mistakes_section_from_turns(turns) is None


def test_weave_places_section_before_self_study():
    content = f"CLASS PART\n\n• a bullet\n\n\n{SELF_STUDY_HEADING}\n\nREST\n\n• more"
    woven = weave_mistakes_into_content(content, MISTAKES_HEADING + "\n\n• x")
    assert woven.index(MISTAKES_HEADING) < woven.index(SELF_STUDY_HEADING)
    assert woven.index("CLASS PART") < woven.index(MISTAKES_HEADING)


def test_weave_places_section_before_flat_marker():
    content = f"Segment title\nline\n\n{CLASS_END_MARKER}\nrest"
    woven = weave_mistakes_into_content(content, MISTAKES_HEADING + "\n\n• x")
    assert woven.index(MISTAKES_HEADING) < woven.index(CLASS_END_MARKER)


def test_weave_appends_when_lesson_fully_covered():
    woven = weave_mistakes_into_content("CLASS ONLY\n\n• bullet", MISTAKES_HEADING + "\n\n• x")
    assert woven.endswith(MISTAKES_HEADING + "\n\n• x")
