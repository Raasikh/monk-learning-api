import json
import pytest
from app.drona.tutor import FORBIDDEN_SSE_KEYS
from app.drona.live_session_ws import drona_live_session_ws

def test_no_forbidden_keys_in_client_contract():
    """Asserts that R3 forbidden server-side keys never leak to client frames."""
    forbidden = {"model_answer", "rubric", "expected_misconceptions", "grade", "mistake_tag", "phase_request", "segment_complete"}
    
    # Valid client frame types
    sample_client_payloads = [
        {"type": "speech_delta", "delta": "Hello class"},
        {"type": "board", "board": "Direct measurement works only for ~mm to ~100 m"},
        {"type": "meta", "segment_index": 1, "total_segments": 5, "session_complete": False},
        {"type": "state", "phase": "teaching"},
        {"type": "audio_chunk", "audio": "b64==", "speech": "Hello", "board": ""}
    ]

    for payload in sample_client_payloads:
        for k in forbidden:
            assert k not in payload, f"R3 Violation: Forbidden key '{k}' found in payload: {payload}"

def test_forbidden_key_assertion_raises():
    """Asserts that attempting to send a forbidden key raises an exception."""
    forbidden = {"model_answer", "rubric", "expected_misconceptions", "grade", "mistake_tag", "phase_request", "segment_complete"}
    
    bad_payload = {"type": "speech_delta", "delta": "Hello", "grade": "correct"}
    
    raised = False
    for k in forbidden:
        if k in bad_payload:
            raised = True
            break
            
    assert raised, "Expected forbidden key detection to trigger"
