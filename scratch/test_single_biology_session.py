import asyncio
import os
import time
import requests
from dotenv import load_dotenv
from scripts.full_session_harness import FullSessionHarness, mint_real_supabase_jwt, SUBJECT_HARNESS_SPECS

load_dotenv('.env')
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

async def test_bio():
    token = mint_real_supabase_jwt()
    bio_spec = [s for s in SUBJECT_HARNESS_SPECS if s["subject"] == "Biology"][0]
    harness = FullSessionHarness(bio_spec, wrong_answer_variant=False, jwt_token=token)
    await harness.run()

if __name__ == "__main__":
    asyncio.run(test_bio())
