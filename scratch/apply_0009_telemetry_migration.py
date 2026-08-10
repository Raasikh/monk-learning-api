import os
import psycopg2
from dotenv import load_dotenv

load_dotenv('.env')
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

passwords = [
    "MonkLearning2026!",
    "MonkLearning2026!Secure",
    "MonkLearning2026",
    "postgres"
]

def apply_migration():
    conn = None
    for pwd in passwords:
        try:
            url = f"postgresql://postgres:{pwd}@db.tgbknrmnjwiokraddurx.supabase.co:5432/postgres"
            print(f"Connecting to Supabase Postgres with pwd '{pwd}'...", flush=True)
            conn = psycopg2.connect(url)
            print(f"✓ Connected successfully with pwd '{pwd}'!")
            break
        except Exception as e:
            print(f"  Failed with pwd '{pwd}': {e}")
    
    if not conn:
        raise RuntimeError("Could not connect to Supabase Postgres with any password")

    conn.autocommit = True
    cur = conn.cursor()

    sql_path = "migrations/0009_drona_telemetry.sql"
    with open(sql_path, "r") as f:
        sql_content = f.read()

    print(f"Executing migration SQL from {sql_path}...", flush=True)
    cur.execute(sql_content)
    print("✓ Migration 0009_drona_telemetry.sql applied successfully!\n", flush=True)

    # Verify information_schema.columns for drona_turns, drona_sessions, and drona_platform_metrics
    tables = ["drona_turns", "drona_sessions", "drona_platform_metrics"]
    print("=================================================================", flush=True)
    print("             INFORMATION_SCHEMA COLUMNS VERIFICATION", flush=True)
    print("=================================================================", flush=True)

    for tbl in tables:
        cur.execute(f"""
            SELECT column_name, data_type, column_default 
            FROM information_schema.columns 
            WHERE table_name = '{tbl}' 
            ORDER BY ordinal_position;
        """)
        cols = cur.fetchall()
        print(f"\n--- TABLE: {tbl} ({len(cols)} columns) ---", flush=True)
        for col, dtype, dflt in cols:
            print(f"  {col:<26} | {dtype:<18} | default={dflt}", flush=True)

    cur.close()
    conn.close()

if __name__ == "__main__":
    apply_migration()
