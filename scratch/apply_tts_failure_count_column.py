import os
import psycopg2
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

# DB Connection string from environment
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or "postgresql://postgres.tgbknrmnjwiokraddurx:MonkLearning2026!@aws-0-us-east-1.pooler.supabase.com:6543/postgres"

def apply_migration():
    print("Connecting to Supabase Postgres...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()

    sql = "ALTER TABLE drona_turns ADD COLUMN IF NOT EXISTS tts_failure_count INT DEFAULT 0;"
    print("Executing SQL:", sql)
    cur.execute(sql)
    print("Migration applied successfully!")

    cur.close()
    conn.close()

if __name__ == "__main__":
    apply_migration()
