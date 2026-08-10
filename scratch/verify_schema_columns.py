import os
from app.db import supabase

def verify_new_telemetry_columns():
    print("=================================================================", flush=True)
    print("       CONFIRMING TELEMETRY MIGRATION 0009 SCHEMAS IN DB        ", flush=True)
    print("=================================================================", flush=True)

    # 1. drona_turns additions check
    print("\n--- TABLE: drona_turns ---", flush=True)
    res_turns = supabase.table("drona_turns").select("rumik_requests, rumik_chars, board_event_count, tts_ms, llm_ms, violations").limit(1).execute()
    print("  ✓ Columns verified on drona_turns: rumik_requests, rumik_chars, board_event_count, tts_ms, llm_ms, violations")
    print(f"    Sample query output: {res_turns.data}")

    # 2. drona_sessions additions check
    print("\n--- TABLE: drona_sessions ---", flush=True)
    res_sess = supabase.table("drona_sessions").select("rumik_requests_total, rumik_peak_rpm, pool_exhaustion_count, segments_completed, ended_reason").limit(1).execute()
    print("  ✓ Columns verified on drona_sessions: rumik_requests_total, rumik_peak_rpm, pool_exhaustion_count, segments_completed, ended_reason")
    print(f"    Sample query output: {res_sess.data}")

    # 3. drona_platform_metrics check
    print("\n--- TABLE: drona_platform_metrics ---", flush=True)
    res_plat = supabase.table("drona_platform_metrics").select("id, sampled_at, active_sessions, rumik_connections_open, rumik_requests_last_60s, sarvam_requests_last_60s, pool_wait_ms_p95").limit(1).execute()
    print("  ✓ Table verified: drona_platform_metrics (id, sampled_at, active_sessions, rumik_connections_open, rumik_requests_last_60s, sarvam_requests_last_60s, pool_wait_ms_p95)")
    print(f"    Sample query output: {res_plat.data}")

if __name__ == "__main__":
    verify_new_telemetry_columns()
