from app.db import supabase

def audit_migrations():
    print("=== MIGRATION AUDIT REPORT (0005 ONWARD) ===")

    # 0005: drona_sessions, drona_plans, drona_turns, lesson_plans, subtopic_index
    tables_0005 = ["drona_sessions", "drona_plans", "drona_turns", "lesson_plans", "subtopic_index"]
    print("\n--- 0005_drona.sql ---")
    for t in tables_0005:
        try:
            res = supabase.table(t).select("id").limit(1).execute()
            print(f"  ✅ Table '{t}' EXISTS")
        except Exception as e:
            print(f"  ❌ Table '{t}' MISSING ({e})")

    # 0006: chapter_aliases
    print("\n--- 0006_chapter_aliases.sql ---")
    try:
        res = supabase.table("chapter_aliases").select("id").limit(1).execute()
        print("  ✅ Table 'chapter_aliases' EXISTS")
    except Exception as e:
        print(f"  ❌ Table 'chapter_aliases' MISSING ({e})")

    # 0007: drona_wellbeing_flags, drona_rate_limits, drona_turns.tts_failure_count
    print("\n--- 0007_drona_voice.sql ---")
    for t in ["drona_wellbeing_flags", "drona_rate_limits"]:
        try:
            res = supabase.table(t).select("id").limit(1).execute()
            print(f"  ✅ Table '{t}' EXISTS")
        except Exception as e:
            print(f"  ❌ Table '{t}' MISSING ({e})")

    # 0008: Telemetry columns
    print("\n--- 0008_drona_telemetry.sql (Columns) ---")
    cols_to_check = {
        "drona_sessions": ["mute_duration_sec", "stt_seconds", "tts_characters", "reconnect_count"],
        "drona_turns": ["tts_failure_count"]
    }
    for table, cols in cols_to_check.items():
        for col in cols:
            try:
                res = supabase.table(table).select(col).limit(1).execute()
                print(f"  ✅ Column '{table}.{col}' EXISTS")
            except Exception as e:
                print(f"  ❌ Column '{table}.{col}' MISSING")

if __name__ == "__main__":
    audit_migrations()
