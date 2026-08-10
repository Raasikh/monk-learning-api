from typing import Dict, Any, Tuple

def compute_next_session_state(
    current_phase: str,
    current_segment: int,
    total_segments: int,
    attempts: int,
    tutor_output: Dict[str, Any],
    turn_type: str
) -> Tuple[str, int, int, bool, bool]:
    """
    Backend-enforced State Machine (§5).
    Returns (next_phase, next_segment, next_attempts, segment_advanced, is_mistake).
    """
    # Rule: turn_type of interruption or no_response -> phase does not change, segment does not advance
    if turn_type in ("interruption", "no_response"):
        return current_phase, current_segment, attempts, False, False

    phase_req = tutor_output.get("phase_request", current_phase)
    grade = (tutor_output.get("grade") or "").lower().strip()
    seg_complete = bool(tutor_output.get("segment_complete"))
    offtopic_tier = tutor_output.get("offtopic_tier")

    # Immediate completion on end_session request or crisis offtopic (tier 5)
    if phase_req == "end_session" or offtopic_tier == 5:
        return "complete", current_segment, 0, False, False

    # Transition to wrapup when phase_req is wrapup
    if phase_req == "wrapup":
        return "wrapup", current_segment, 0, False, False

    # 1. State: Wrapup
    if current_phase == "wrapup":
        return "complete", current_segment, 0, False, False

    # 2. State: Awaiting Answer (end-of-segment quiz)
    #
    # A segment ends with a short 3-question quiz. Every answer moves straight
    # on to the next question — right or wrong, the tutor says so and explains,
    # but never re-asks; the quiz is meant to be quick. Only the LAST question
    # closes the segment.
    #
    # `_final_quiz_question` is set by the backend in tutor.py, not by the model.
    # Without it, grading question 1 advanced the segment and questions 2 and 3
    # were never asked.
    if current_phase == "awaiting_answer":
        if grade in ("correct", "partial", "incorrect"):
            is_mistake = grade in ("partial", "incorrect")

            if not bool(tutor_output.get("_final_quiz_question")):
                # More quiz questions to come — hold the segment, keep asking.
                return "awaiting_answer", current_segment, 0, False, is_mistake

            next_seg = current_segment + 1
            if next_seg > total_segments:
                return "wrapup", current_segment, 0, True, is_mistake
            return "teaching", next_seg, 0, True, is_mistake
        else:
            # No grade. An unparsed grade must NEVER default to correct or
            # advance the segment — that rule is absolute and still holds here.
            #
            # But a *deliberate* null (the reply was to a lightweight check or
            # a procedural question, not to the graded checkpoint) has to hand
            # control back to teaching. Leaving the phase at awaiting_answer
            # meant every ungraded check re-entered this branch, so the segment
            # sat on turn 1 forever posting new checks and never reached its
            # checkpoint. Returning to teaching does not advance the segment
            # and does not record a grade.
            if phase_req == "teaching":
                return "teaching", current_segment, attempts, False, False
            return current_phase, current_segment, attempts, False, False

    # 3. State: Teaching
    if current_phase == "teaching":
        if phase_req == "awaiting_answer":
            return "awaiting_answer", current_segment, attempts, False, False
        
        if seg_complete:
            next_seg = current_segment + 1
            if next_seg > total_segments:
                return "wrapup", current_segment, 0, True, False
            return "teaching", next_seg, 0, True, False

    return current_phase, current_segment, attempts, False, False
