import os
import requests
from dotenv import load_dotenv, dotenv_values

load_dotenv('.env')
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

sp_url = "https://tgbknrmnjwiokraddurx.supabase.co"
sp_key = (os.getenv("SUPABASE_SECRET_KEY") or "").strip("\"'")

sql = "ALTER TABLE drona_sessions ADD COLUMN IF NOT EXISTS rate_limit_hits SMALLINT DEFAULT 0;"

headers = {
    "apikey": sp_key,
    "Authorization": f"Bearer {sp_key}",
    "Content-Type": "application/json"
}

res = requests.post(f"{sp_url}/rest/v1/rpc/exec_sql", json={"query": sql}, headers=headers)
print("Migration 0010 RPC status:", res.status_code, "text:", res.text)
