import os
import requests

supabase_url = "https://tgbknrmnjwiokraddurx.supabase.co"
supabase_secret = os.getenv("SUPABASE_SECRET_KEY", "")

headers = {
    'apikey': supabase_secret,
    'Authorization': f'Bearer {supabase_secret}',
    'Content-Type': 'application/json'
}

with open("migrations/0009_drona_telemetry.sql", "r") as f:
    sql_query = f.read()

res = requests.post(f"{supabase_url}/rest/v1/rpc/exec_sql", json={"query": sql_query}, headers=headers)
print("Status:", res.status_code)
print("Response:", res.text)
