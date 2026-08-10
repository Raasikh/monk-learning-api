import asyncio
import json
import websockets
import requests
import time

API_BASE_URL = "http://localhost:8000"

async def drive_full_session(subject_name, chapter_id, utterance):
    print(f"\n=================================================================")
    print(f"▶ DRIVING 9-SEGMENT SESSION TO COMPLETION: [{subject_name.upper()}]")
    print(f"=================================================================")

    resp = requests.post(f"{API_BASE_URL}/drona/session/start", json={
        "chapter_id": chapter_id,
        "language": "hinglish",
        "mode": "standard",
        "prompt_version": "v1"
    }, headers={"Authorization": "Bearer e2e_mock_token_123"})
    
    sess_data = resp.json()
    session_id = sess_data["session_id"]
    print(f"  ✓ Session Created: {session_id}")

    s_resp = requests.post(f"{API_BASE_URL}/drona/session/{session_id}/scope", json={
        "utterance": utterance
    }, headers={"Authorization": "Bearer e2e_mock_token_123"})
    
    scope_data = s_resp.json()
    print(f"  ✓ Scoping Response: phase = '{scope_data.get('phase')}', subtopic = '{scope_data.get('subtopic_key')}'")

    ws_url = f"ws://localhost:8000/drona/session/{session_id}/live?token=e2e_mock_token_123"
    
    async with websockets.connect(ws_url, open_timeout=15) as ws:
        print("  ✓ WebSocket Connected! Driving turn transitions...")
        curr_segment = 1
        curr_phase = "teaching"
        start_time = time.time()
        
        # Trigger initial teaching turn
        await ws.send(json.dumps({"action": "start_turn"}))
        
        while curr_phase != "complete" and time.time() - start_time < 300:
            try:
                frame_raw = await asyncio.wait_for(ws.recv(), timeout=60)
                if isinstance(frame_raw, str):
                    frame = json.loads(frame_raw)
                    msg_type = frame.get("type")

                    if msg_type == "state":
                        prev_phase = curr_phase
                        curr_phase = frame.get("phase", curr_phase)
                        curr_segment = frame.get("current_segment", curr_segment)
                        print(f"  [STATE] Segment {curr_segment}/9 | Phase: {curr_phase}")

                        if curr_phase == "awaiting_answer" and prev_phase != "awaiting_answer":
                            opts = frame.get("check_options", [])
                            ans = opts[0] if opts else "Option A"
                            print(f"  ⚡ [CHECKPOINT QUIZ] Answering Segment {curr_segment}: '{ans}'")
                            await ws.send(json.dumps({"action": "answer", "text": ans}))

                        elif curr_phase == "teaching" and prev_phase == "awaiting_answer":
                            print(f"  🚀 [SEGMENT ADVANCE] Phase advanced to 'teaching' for Segment {curr_segment}!")
                            await ws.send(json.dumps({"action": "start_turn"}))

                    elif msg_type == "turn_complete":
                        print(f"  ✓ Turn Complete for Segment {curr_segment}")

            except asyncio.TimeoutError:
                print(f"  ⚠️ Timeout waiting for frame at Segment {curr_segment}")
                break

        print(f"\n=================================================================")
        print(f"🎉 SESSION ADVANCED THROUGH ALL SEGMENTS TO PHASE: '{curr_phase.upper()}'!")
        print(f"=================================================================")

if __name__ == "__main__":
    asyncio.run(drive_full_session("Chemistry", "862ab5f0-4fa8-5e6f-98d5-74fe5b10ab8e", "vsepr-theory-valence-bond-theory-hybridization"))
