"""Verifies migration 0012 against the database, not against the file.

AGENTS.md Rule 9: a migration is applied when the database says so. 0007 and
0008 were both reported applied and were not.

This project has no `exec_sql` RPC and no Postgres connection string on hand, so
the DDL must be pasted into the Supabase SQL editor. This script reports, per
table and per column, what actually landed. Every check prints its own line.

Also checks the Cloudflare R2 configuration the snap pipeline needs, since a
missing bucket is just as capable of breaking Snap a Doubt as a missing column.
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import supabase  # noqa: E402
import app.storage_r2 as r2  # noqa: E402

MIGRATION = os.path.join(os.path.dirname(__file__), "..", "migrations",
                         "0012_notes_and_doubts.sql")

EXPECTED = {
    "notes": (
        "id, user_id, subject, chapter, concept, content, created_at, "
        "session_id, chapter_id, board_items, segments_covered, total_segments, "
        "item_count, session_started_at"
    ),
    "doubts": (
        "id, user_id, subject, chapter, concept, question_text, explanation, solved, "
        "created_at, submission_id, question_index, image_key, legible, "
        "legibility_note, answer, steps, key_idea, status, failure_reason, "
        "transcriber_model, solver_model, transcribe_ms, latency_ms, "
        "question_type, printed_answer, option_labels"
    ),
    "doubt_reports": "id, doubt_id, user_id, comment, created_at",
}

# Columns the old stub carried that 0012 must have removed.
RETIRED = {
    "doubts": ["image_url", "transcribed_question", "question_latex",
               "answer_json", "chapter_name"],
}

failures = 0


def check_table(table: str, columns: str) -> bool:
    """Selecting a column that does not exist returns a PGRST error naming it."""
    global failures
    try:
        supabase.table(table).select(columns).limit(1).execute()
        print(f"  PASS  {table}: all {len(columns.split(','))} expected columns present")
        return True
    except Exception as err:
        failures += 1
        # Narrow it: is the table missing, or only some columns?
        try:
            supabase.table(table).select("id").limit(1).execute()
            missing = []
            for col in [c.strip() for c in columns.split(",")]:
                try:
                    supabase.table(table).select(col).limit(1).execute()
                except Exception:
                    missing.append(col)
            print(f"  FAIL  {table}: table exists, missing columns {missing}")
        except Exception:
            print(f"  FAIL  {table}: table does not exist")
        print(f"        raw error: {str(err)[:200]}")
        return False


def check_r2() -> None:
    """Names follow the dronav1project convention, which already holds working
    credentials for this Cloudflare account."""
    global failures
    if not r2.is_configured():
        failures += 1
        print("  FAIL  R2 not configured for this process.")
        print("        Needs R2_ENDPOINT_URL (or R2_ACCOUNT_ID), R2_ACCESS_KEY_ID,")
        print("        R2_SECRET_ACCESS_KEY, and R2_DOUBTS_BUCKET_NAME (or R2_BUCKET_NAME).")
        print("        POST /doubts returns 503 until these are set.")
        return

    if not (os.getenv("R2_DOUBTS_BUCKET_NAME") or "").strip():
        print("  WARN  R2_DOUBTS_BUCKET_NAME is not set — snapped student photos")
        print(f"        would go to the shared bucket '{r2.bucket_name()}'.")

    try:
        r2.get_client().head_bucket(Bucket=r2.bucket_name())
        print(f"  PASS  R2 bucket '{r2.bucket_name()}' reachable")
    except Exception as err:
        failures += 1
        print(f"  FAIL  R2 bucket unreachable: {str(err)[:200]}")


if __name__ == "__main__":
    print(f"Supabase project: {(os.getenv('SUPABASE_URL') or '').rstrip('/')}\n")

    print("--- Tables (paste migrations/0012_notes_and_doubts.sql into the SQL editor) ---")
    all_ok = True
    for table, columns in EXPECTED.items():
        all_ok = check_table(table, columns) and all_ok

    print("\n--- Retired stub columns (0012 must have dropped these) ---")
    for table, cols in RETIRED.items():
        for col in cols:
            try:
                supabase.table(table).select(col).limit(1).execute()
                failures += 1
                print(f"  FAIL  {table}.{col} still exists — 0012 did not reshape the stub")
            except Exception:
                print(f"  PASS  {table}.{col} is gone")

    print("\n--- Cloudflare R2 (Snap It Out image storage) ---")
    check_r2()

    if not all_ok:
        print("\n" + "=" * 72)
        print("ACTION REQUIRED — paste this file into the Supabase SQL editor:")
        print(f"  {os.path.abspath(MIGRATION)}")
        print("Then re-run this script. It is not applied until these checks pass.")
        print("=" * 72)

    print(f"\nRESULT: {failures} failed check(s)")
    sys.exit(1 if failures else 0)
