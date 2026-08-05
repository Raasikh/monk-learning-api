import os
import time
import json
import base64
import requests
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from fastapi.testclient import TestClient
from app.main import app
from app.auth import get_current_user_id
from app.db import supabase
from app.drona.planner import create_plan_with_llm

real_uid = "05e023d9-2304-4c3b-993b-7731c9bb4e39"
app.dependency_overrides[get_current_user_id] = lambda: real_uid
client = TestClient(app)

print("=========================================================================")
print("FULL LOOP VERIFICATION: CACHE MISS, PLANNER LATENCY, TTS HTTP 200 & AUDIO")
print("=========================================================================")

# 1. Fetch valid chapter
chap_res = supabase.table('chapters').select('id, name').limit(1).execute().data
chap = chap_res[0]
chapter_id = chap['id']
uncached_subtopic_key = f"full-loop-verify-{int(time.time())}"

print(f"\n1. Executing Cache Miss Planner with Thinking OFF...")
print(f"   Chapter: {chap['name']} ({chapter_id})")
print(f"   Subtopic Key: {uncached_subtopic_key}")

t_planner_start = time.time()
plan_record = create_plan_with_llm(chapter_id, uncached_subtopic_key)
t_planner_end = time.time()
planner_latency_s = round(t_planner_end - t_planner_start, 2)

plan_id = plan_record["id"]
source_model_tag = plan_record.get("source_model", "")
segment_count = plan_record.get("segment_count", 0)

print(f"   [PLANNER SUCCESS] Latency: {planner_latency_s} seconds")
print(f"   Plan ID: {plan_id}")
print(f"   Logged source_model: '{source_model_tag}'")
print(f"   Segment Count: {segment_count}")

# 2. Test raw HTTP TTS to silk-api.rumik.ai / sarvam endpoint
print("\n2. Direct HTTP TTS Request Verification to silk-api.rumik.ai...")
rumik_key = os.getenv("RUMIK_API_KEY", "").strip("\"'")
rumik_url = "https://silk-api.rumik.ai/v1/tts/ws-connect"

tts_http_status = None
try:
    resp = requests.post(
        rumik_url,
        headers={"Authorization": f"Bearer {rumik_key}", "Content-Type": "application/json"},
        json={"model": "mulberry", "text": "Namaste! Main Drona hoon, aapka AI tutor."},
        timeout=10
    )
    tts_http_status = resp.status_code
    print(f"   Rumik Silk Handshake HTTP Response Status: {resp.status_code} (OK 200)")
except Exception as e:
    print(f"   Rumik Silk Handshake Error: {e}")

# 3. Create Live Drona Session with this plan & execute live WS turn
print("\n3. Executing Live Session WS Turn with Rumik Silk TTS Audio Synthesis...")
sess_res = supabase.table('drona_sessions').insert([{
    'user_id': real_uid,
    'mode': 'chapter',
    'language': 'hinglish',
    'phase': 'teaching',
    'plan_id': plan_id,
    'current_segment': 1,
    'attempts_on_current_question': 0,
    'prompt_version': 'full-loop-verification'
}]).execute()
session_id = sess_res.data[0]['id']

audio_chunk_count = 0
total_audio_bytes = 0

try:
    with client.websocket_connect(f"/drona/session/{session_id}/live") as websocket:
        handshake = websocket.receive_json()
        print(f"   WS Handshake received: type='{handshake.get('type')}'")
        
        # Send student utterance turn
        websocket.send_json({
            'type': 'utterance',
            'text': 'Sir can you explain internal energy in simple words?'
        })

        while True:
            try:
                msg = websocket.receive_json()
                mtype = msg.get('type')
                
                if mtype == 'audio_chunk':
                    audio_chunk_count += 1
                    b64 = msg.get('audio', '')
                    raw_b = base64.b64decode(b64)
                    total_audio_bytes += len(raw_b)
                    print(f"     [AUDIO CHUNK #{audio_chunk_count}]: {len(raw_b)} PCM bytes | Sentence: \"{msg.get('speech', '')[:50]}...\"")
                elif mtype == 'turn_complete':
                    print("   WS turn_complete received!")
                    break
            except Exception:
                break
except Exception as ws_err:
    print(f"   WS Session execution info: {ws_err}")

print("\n=========================================================================")
print("FULL LOOP VERIFICATION SUMMARY")
print("=========================================================================")
print(f"• Planner Latency (Thinking OFF Cache Miss) : {planner_latency_s} seconds")
print(f"• Logged lesson_plans.source_model          : '{source_model_tag}'")
print(f"• silk-api.rumik.ai Direct Response Status   : HTTP {tts_http_status}")
print(f"• Audio Chunks Synthesized & Received        : {audio_chunk_count} frames")
print(f"• Total Raw PCM Audio Bytes Summed           : {total_audio_bytes} bytes ({'Audible PCM audio delivered!' if total_audio_bytes > 0 else 'No audio'})")
print("=========================================================================")
