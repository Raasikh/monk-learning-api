"""Applies migrations/0011_drona_tutor_voice.sql and verifies it landed.

Per AGENTS.md Rule 9: a migration is not "applied" until information_schema
says so. This script does both, and prints raw output for both steps.
"""
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip("\"'").rstrip("/")
SUPABASE_KEY = (os.getenv("SUPABASE_SECRET_KEY") or "").strip("\"'")

if not SUPABASE_URL or not SUPABASE_KEY:
    sys.exit("SUPABASE_URL / SUPABASE_SECRET_KEY missing from .env")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

MIGRATION = os.path.join(os.path.dirname(__file__), "..", "migrations", "0011_drona_tutor_voice.sql")

VERIFY_SQL = """
SELECT column_name, data_type, column_default, is_nullable
FROM information_schema.columns
WHERE table_name = 'drona_sessions' AND column_name = 'tutor_voice';
"""


def run_sql(label: str, sql: str):
    res = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
        json={"query": sql},
        headers=HEADERS,
        timeout=30,
    )
    print(f"--- {label} ---")
    print(f"HTTP {res.status_code}")
    print(res.text[:2000] or "(empty body)")
    print()
    return res


if __name__ == "__main__":
    with open(MIGRATION) as fh:
        migration_sql = fh.read()

    apply_res = run_sql("APPLY 0011_drona_tutor_voice.sql", migration_sql)
    verify_res = run_sql("VERIFY information_schema.columns", VERIFY_SQL)

    if apply_res.status_code >= 400 or verify_res.status_code >= 400:
        sys.exit(
            "exec_sql RPC unavailable or errored — apply this migration by hand "
            "in the Supabase SQL editor and re-run the VERIFY query above."
        )
