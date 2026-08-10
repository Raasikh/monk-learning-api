import asyncio
import json
import websockets
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.db import supabase

async def test_e2e_local_session():
    print("=== TESTING END-TO-END LOCAL SESSION EXECUTION ===\n")
    
    # Get active session
    res = supabase.table("drona_sessions").select("id").order("created_at", desc=True).limit(1).execute()
    session_id = res.data[0]["id"]
    print(f"Testing Session ID: {session_id}")

    uri = f"ws://localhost:8000/drona/session/{session_id}/live"
    print(f"Connecting to WebSocket: {uri}...")

    audio_chunks_received = 0
    board_events_received = 0
    state_frames_received = 0
    turn_completed = False

    async with websockets.connect(uri) as ws:
        init_msg = await ws.recv()
        print("Connected frame:", init_msg)

        # Send test utterance
        print("\nSending student utterance: 'Teach me Speed and Velocity.'...")
        await ws.send(json.dumps({
            "type": "utterance",
            "text": "Teach me Speed and Velocity."
        }))

        t0 = asyncio.get_event_loop().time()
        while True:
            try:
                frame = await asyncio.wait_for(ws.recv(), timeout=25.0)
                if isinstance(frame, str):
                    data = json.loads(frame)
                    t_type = data.get("type")

                    if t_type == "audio_chunk":
                        audio_chunks_received += 1
                        if audio_chunks_received == 1:
                            ttfa = asyncio.get_event_loop().time() - t0
                            print(f"✅ [TTFA] First Audio Chunk received in {ttfa:.2f}s! Sentence: \"{data.get('speech')}\"")

                    elif t_type == "board_events":
                        board_events_received += len(data.get("events", []))
                        print(f"✅ [BOARD EVENTS FRAME] Received {len(data.get('events', []))} events")

                    elif t_type == "state":
                        state_frames_received += 1
                        print(f"✅ [STATE FRAME] Phase: {data.get('phase')}, Question Type: {data.get('question_type')}, Options: {data.get('check_options')}")

                    elif t_type == "turn_complete":
                        turn_completed = True
                        print("✅ [TURN COMPLETE] Turn execution complete!")
                        break

            except Exception as exc:
                print("WS loop ended:", exc)
                break

    print(f"\n=== E2E SESSION SUMMARY ===")
    print(f"Audio Chunks Received: {audio_chunks_received}")
    print(f"Board Events Received: {board_events_received}")
    print(f"State Frames Received: {state_frames_received}")
    print(f"Turn Completed Cleanly: {turn_completed}")

if __name__ == "__main__":
    asyncio.run(test_e2e_local_session())
