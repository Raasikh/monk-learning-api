"""Prints a fresh Supabase access token. Called by the browser matrix before
each combo — Supabase access tokens live one hour and a single combo can spend
that long regenerating a purged lesson plan."""
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SECRET = os.getenv("SUPABASE_SECRET_KEY") or ""
EMAIL = os.getenv("E2E_TEST_EMAIL", "raasikh.naveed@gmail.com")

h = {"apikey": SECRET, "Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"}
g = requests.post(f"{URL}/auth/v1/admin/generate_link",
                  json={"type": "magiclink", "email": EMAIL}, headers=h, timeout=20)
if g.status_code != 200:
    sys.exit(f"generate_link failed: {g.status_code}")
v = requests.post(f"{URL}/auth/v1/verify",
                  json={"type": "magiclink", "token": g.json()["email_otp"], "email": EMAIL},
                  headers=h, timeout=20)
if v.status_code != 200:
    sys.exit(f"verify failed: {v.status_code}")
print(v.json()["access_token"])
