import os
import json
import time
from dotenv import load_dotenv

load_dotenv('.env')
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.db import supabase
from app.drona.voice_proxy import split_into_sentences

def analyze_real_session_rumik_metrics():
    print("=========================================================================")
    print("▶ ITEM 2: REAL PRODUCTION RUMIK TTS REQUESTS & CAPACITY AUDIT")
    print("=========================================================================")

    # Query recent production turns from drona_turns
    turns_res = supabase.table('drona_turns').select('session_id, turn_index, raw_response, created_at').order('created_at', desc=True).limit(100).execute()
    turns = turns_res.data or []

    if not turns:
        print("No turns found in drona_turns table.")
        return

    # Group by session_id
    sessions_map = {}
    for t in turns:
        s_id = t['session_id']
        if s_id not in sessions_map:
            sessions_map[s_id] = []
        sessions_map[s_id].append(t)

    # Pick the session with the most turns (the full 9-segment Physics session)
    target_sid = max(sessions_map.keys(), key=lambda k: len(sessions_map[k]))
    target_turns = sorted(sessions_map[target_sid], key=lambda x: x['turn_index'])

    print(f"Target Session ID: {target_sid}")
    print(f"Total Turns in Session: {len(target_turns)}")

    total_rumik_requests_40 = 0
    total_rumik_requests_100 = 0
    req_timestamps_100 = []

    print("\n--- TURN-BY-TURN BREAKDOWN ---")
    for t in target_turns:
        t_idx = t['turn_index']
        raw = t.get('raw_response') or '{}'
        try:
            parsed = json.loads(raw)
            speech = parsed.get('speech', '')
        except Exception:
            speech = ''

        chunks_40 = split_into_sentences(speech, min_chars=40)
        chunks_100 = split_into_sentences(speech, min_chars=100)

        total_rumik_requests_40 += len(chunks_40)
        total_rumik_requests_100 += len(chunks_100)

        print(f"Turn #{t_idx:2d} ({len(speech.split())} words, {len(speech)} chars) -> {len(chunks_40)} reqs (40-char min) | {len(chunks_100)} reqs (100-char min)")

        # Estimate timestamp of each request during the turn
        from datetime import datetime
        created_str = t.get('created_at')
        if created_str:
            dt = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
            t_base = dt.timestamp()
        else:
            t_base = time.time()

        for c_i, c in enumerate(chunks_100):
            req_timestamps_100.append(t_base + c_i * 4.0)

    avg_req_per_turn_40 = total_rumik_requests_40 / len(target_turns)
    avg_req_per_turn_100 = total_rumik_requests_100 / len(target_turns)

    # Compute peak requests in any rolling 60-second window
    peak_60s_100 = 0
    for ts in req_timestamps_100:
        count = sum(1 for x in req_timestamps_100 if ts <= x < ts + 60.0)
        if count > peak_60s_100:
            peak_60s_100 = count

    capacity_concurrent = int(100 / peak_60s_100) if peak_60s_100 > 0 else 0

    print("\n=========================================================================")
    print("▶ REAL PRODUCTION RUMIK TTS METRICS SUMMARY")
    print("=========================================================================")
    print(f"  • Total Turns Executed:               {len(target_turns)} turns")
    print(f"  • Total Rumik Requests (40-char min): {total_rumik_requests_40} requests ({avg_req_per_turn_40:.2f} reqs/turn)")
    print(f"  • Total Rumik Requests (100-char min):{total_rumik_requests_100} requests ({avg_req_per_turn_100:.2f} reqs/turn)")
    print(f"  • Peak Requests in Rolling 60s Window:{peak_60s_100} requests/min")
    print(f"  • Real Concurrent Student Capacity:   {capacity_concurrent} active students (100 RPM ceiling)")

if __name__ == "__main__":
    analyze_real_session_rumik_metrics()
