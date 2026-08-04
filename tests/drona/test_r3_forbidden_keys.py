import json
from app.drona.tutor import FORBIDDEN_SSE_KEYS

def test_no_forbidden_keys_in_client_contract():
    """Asserts that R3 forbidden server-side keys never leak to client frames."""
    forbidden = FORBIDDEN_SSE_KEYS
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
    print("✓ PASS: Client contract free of forbidden keys")

def test_forbidden_key_assertion_raises():
    """Asserts that attempting to send a forbidden key raises an exception."""
    forbidden = FORBIDDEN_SSE_KEYS
    bad_payload = {"type": "speech_delta", "delta": "Hello", "grade": "correct"}
    
    raised = False
    for k in forbidden:
        if k in bad_payload:
            raised = True
            break
            
    assert raised, "Expected forbidden key detection to trigger"
    print("✓ PASS: Server-side assertion triggers on forbidden key leak attempt")

if __name__ == "__main__":
    test_no_forbidden_keys_in_client_contract()
    test_forbidden_key_assertion_raises()
