import os
import json
import requests
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.db import supabase

def check_or_add_column():
    try:
        res = supabase.table("drona_turns").select("id, tts_failure_count").limit(1).execute()
        print("Column drona_turns.tts_failure_count exists!", res.data)
    except Exception as e:
        print("Column drona_turns.tts_failure_count missing or error:", e)

if __name__ == "__main__":
    check_or_add_column()
