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

    # Ignore wrapup phase_request unless on final segment
    if phase_req == "wrapup" and current_segment < total_segments:
        phase_req = current_phase

    # 1. State: Wrapup
    if current_phase == "wrapup":
        return "complete", current_segment, 0, False, False

    # 2. State: Awaiting Answer (Checkpoint evaluation)
    if current_phase == "awaiting_answer":
        if grade == "correct":
            next_seg = current_segment + 1
            if next_seg > total_segments:
                return "wrapup", current_segment, 0, True, False
            return "teaching", next_seg, 0, True, False

        elif grade == "partial":
            next_seg = current_segment + 1
            if next_seg > total_segments:
                return "wrapup", current_segment, 0, True, True
            return "teaching", next_seg, 0, True, True

        elif grade == "incorrect":
            if attempts == 0:
                return "awaiting_answer", current_segment, 1, False, True
            else:
                # Max 1 attempt reached -> advance segment
                next_seg = current_segment + 1
                if next_seg > total_segments:
                    return "wrapup", current_segment, 0, True, True
                return "teaching", next_seg, 0, True, True
        else:
            # Fallback if grade is absent/unrecognized during awaiting_answer: default to correct & advance segment
            next_seg = current_segment + 1
            if next_seg > total_segments:
                return "wrapup", current_segment, 0, True, False
            return "teaching", next_seg, 0, True, False

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
