import os
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.db import supabase

def verify_columns():
    print("=== VERIFYING DRONA DB SCHEMA COLUMNS ===")

    # 1. Test drona_sessions columns
    try:
        res_sess = supabase.table("drona_sessions").select("id, stt_seconds, tts_characters, reconnect_count, mute_duration_sec").limit(1).execute()
        print("✅ drona_sessions.mute_duration_sec EXISTS! Data:", res_sess.data)
    except Exception as e:
        print("❌ drona_sessions.mute_duration_sec MISSING or error:", e)

    # 2. Test drona_turns columns
    try:
        res_turns = supabase.table("drona_turns").select("id, tts_failure_count").limit(1).execute()
        print("✅ drona_turns.tts_failure_count EXISTS! Data:", res_turns.data)
    except Exception as e:
        print("❌ drona_turns.tts_failure_count MISSING or error:", e)

if __name__ == "__main__":
    verify_columns()
