"""compute_reteach_state excludes "teach me again" turns from the segment's
turn count, so a re-teach doesn't silently burn one of its
QUIZ_QUESTIONS_PER_SEGMENT slots. That exclusion depends entirely on each
prior turn dict carrying an "utterance" key — the caller's select() once
omitted that column, so prior_reteaches was always 0 in production and every
re-teach turn advanced effective_turn exactly like a real answer would."""

from app.drona.tutor import compute_reteach_state, MAX_RETEACHES_PER_SEGMENT


def test_no_reteach_effective_turn_tracks_turn_within_segment():
    state = compute_reteach_state(utterance="the answer is LT^-1", seg_turns=[], turn_within_segment=1)
    assert state.is_reteach_request is False
    assert state.prior_reteaches == 0
    assert state.do_reteach is False
    assert state.effective_turn == 1


def test_reteach_request_holds_the_current_slice():
    # Turn 2 asks to be taught again — the slice must not advance to turn 2's
    # content; it must hold at turn 1's.
    state = compute_reteach_state(utterance="teach me again please", seg_turns=[], turn_within_segment=2)
    assert state.is_reteach_request is True
    assert state.do_reteach is True
    assert state.effective_turn == 1


def test_prior_reteach_turns_are_excluded_from_the_count():
    # Turn 3 is a real answer. One prior turn (turn 2) was a re-teach request.
    # Without exclusion, effective_turn would be 3 (turn_within_segment) — as
    # if the re-teach had consumed a real quiz slot. With exclusion it must
    # read back as turn 2, i.e. the re-teach never happened for slicing
    # purposes.
    seg_turns = [
        {"utterance": "the answer is LT^-1"},  # turn 1: real answer
        {"utterance": "phir se samjhao please"},  # turn 2: re-teach request
    ]
    state = compute_reteach_state(utterance="ok now I get it, MLT^-2", seg_turns=seg_turns, turn_within_segment=3)
    assert state.prior_reteaches == 1
    assert state.is_reteach_request is False
    assert state.effective_turn == 2


def test_utterance_missing_from_seg_turns_rows_is_the_regression_this_guards():
    # This is exactly the bug: if the caller's select() forgot the "utterance"
    # column, every row here would arrive as {} instead of {"utterance": ...},
    # and prior_reteaches would silently stay 0 no matter how many re-teach
    # turns actually happened.
    seg_turns_missing_column = [{}, {}]  # two prior turns, neither exposing utterance
    state = compute_reteach_state(utterance="a fresh answer", seg_turns=seg_turns_missing_column, turn_within_segment=3)
    assert state.prior_reteaches == 0
    assert state.effective_turn == 3  # uncorrected — this is the failure mode, not the fix


def test_reteach_exhausted_after_max_reteaches():
    seg_turns = [{"utterance": "teach me again"} for _ in range(MAX_RETEACHES_PER_SEGMENT)]
    state = compute_reteach_state(
        utterance="explain that again",
        seg_turns=seg_turns,
        turn_within_segment=MAX_RETEACHES_PER_SEGMENT + 2,
    )
    assert state.prior_reteaches == MAX_RETEACHES_PER_SEGMENT
    assert state.reteach_exhausted is True
    # A third re-teach request is still detected as one, but must not be acted on.
    assert state.is_reteach_request is True
    assert state.do_reteach is False
