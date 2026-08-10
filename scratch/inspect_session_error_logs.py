import os
from app.db import supabase

session_ids = [
    '211cf8d1-637b-40af-a1c5-567c53bc6545', # Physics
    '2d45f66f-af54-4f17-b630-57b81d241418', # Chemistry
    '34304d26-8a11-48d0-8bd7-5893dc9552ff'  # Maths
]

for s_id in session_ids:
    print(f"\n=================================================================", flush=True)
    print(f"SESSION INSPECTION: {s_id}", flush=True)
    print(f"=================================================================", flush=True)
    sess_res = supabase.table("drona_sessions").select("*").eq("id", s_id).execute()
    if sess_res.data:
        s = sess_res.data[0]
        print(f"  Phase: {s.get('phase')} | Seg: {s.get('current_segment')} | Plan ID: {s.get('plan_id')}", flush=True)
        print(f"  History: {s.get('history_summary')}", flush=True)
    
    turns_res = supabase.table("drona_turns").select("turn_index, phase_in, utterance, grade, raw_response, violations").eq("session_id", s_id).order("turn_index").execute()
    print(f"  Total Turns Inserted: {len(turns_res.data or [])}", flush=True)
    for t in turns_res.data or []:
        print(f"    Turn #{t.get('turn_index')}: phase_in={t.get('phase_in')}, grade={t.get('grade')}, viols={t.get('violations')}, raw_response_len={len(t.get('raw_response') or '')}", flush=True)
