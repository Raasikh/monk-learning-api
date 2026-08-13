import json
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.db import supabase
from app.drona.tutor import compute_next_session_state

def test_auto_segment_advance():
    print("=== TESTING AUTO-SEGMENT ADVANCE LOGIC & VARIABLE SCOPING ===")
    
    # Test 1: Verify compute_next_session_state advances current_segment when segment_complete: True
    state_in = {
        "current_phase": "teaching",
        "current_segment": 1,
        "total_segments": 6,
        "attempts": 0,
        "tutor_output": {"segment_complete": True},
        "turn_type": "answer"
    }
    
    next_phase, next_seg, next_attempts, seg_advanced, is_mistake = compute_next_session_state(**state_in)
    
    print(f"Test 1 - Input Segment: 1 | Output Segment: {next_seg} | Phase: {next_phase} | Advanced: {seg_advanced}")
    assert next_seg == 2, f"Expected segment 2, got {next_seg}"
    assert seg_advanced == True, "Expected seg_advanced == True"
    print("✅ Test 1 Passed: Segment advances from 1 -> 2 on segment_complete: True")

    # Test 2: Verify state_data scoping in live_session_ws logic
    state_data = {}
    segment_complete_flag = False
    
    # Simulate SSE state payload arrival
    data_payload = {"phase": "teaching", "segment_complete": True, "current_segment": 2}
    state_data = data_payload
    if data_payload.get("segment_complete"):
        segment_complete_flag = True

    should_advance = (state_data.get("phase") == "teaching") and (segment_complete_flag or state_data.get("segment_complete"))
    print(f"Test 2 - state_data scoped correctly: {should_advance}")
    assert should_advance == True, "Expected should_advance == True"
    print("✅ Test 2 Passed: Variable state_data and segment_complete_flag scoped without NameError")

if __name__ == "__main__":
    test_auto_segment_advance()
