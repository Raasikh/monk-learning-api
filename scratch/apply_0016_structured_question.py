"""Verifies migration 0016 against the database, not against the file.

AGENTS.md Rule 9: a migration is applied when the database says so.
No exec_sql RPC exists on this project (checked live, 404), so the DDL in
migrations/0016_doubts_structured_question.sql must be pasted into the
Supabase SQL editor by hand. This script confirms it landed.
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import supabase  # noqa: E402

MIGRATION = os.path.join(os.path.dirname(__file__), "..", "migrations",
                         "0016_doubts_structured_question.sql")

if __name__ == "__main__":
    failures = 0
    for col in ("stem", "options"):
        try:
            supabase.table("doubts").select(col).limit(1).execute()
            print(f"  PASS  doubts.{col} exists")
        except Exception as err:
            failures += 1
            print(f"  MISSING  doubts.{col}: {str(err)[:150]}")

    if failures:
        print("\n" + "=" * 72)
        print("ACTION REQUIRED — paste this file into the Supabase SQL editor:")
        print(f"  {os.path.abspath(MIGRATION)}")
        print("Then re-run this script.")
        print("=" * 72)

    print(f"\nRESULT: {failures} failed check(s)")
    sys.exit(1 if failures else 0)
