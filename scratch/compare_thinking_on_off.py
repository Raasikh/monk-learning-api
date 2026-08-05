import os
import time
import json
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.db import supabase
from app.drona.retrieval import retrieve_dual_blocks
from app.drona.prompt_loader import load_prompt
from app.drona.models import get_drona_client, get_model_name
from app.drona.planner import strip_fences, repair_json_escapes

print("=========================================================================")
print("SIDE-BY-SIDE PLANNER COMPARISON: THINKING ON vs THINKING OFF")
print("=========================================================================")

chap_res = supabase.table("chapters").select("id, name, subject").limit(1).execute()
chap = chap_res.data[0]
chapter_id = chap["id"]
subtopic_key = "first-law-thermodynamics-bench"
sub_title = "First Law of Thermodynamics & Internal Energy"

structure_block, depth_block, is_grounded = retrieve_dual_blocks(chapter_id, sub_title)
planner_prompt = load_prompt("planner.md")
model_name = get_model_name("planner")

user_prompt = f"""
Chapter: {chap['name']} ({chap['subject']})
Subtopic: {sub_title} (Key: {subtopic_key})

{structure_block}

{depth_block}

Author a complete lesson plan JSON following the instructions in the system prompt.
"""

client = get_drona_client()

# ─── RUN 1: THINKING ON (DEFAULT) ───
print("\n[RUN 1] Calling DeepSeek V4-Pro with Thinking ON...")
t0 = time.time()
res_on = client.chat.completions.create(
    model=model_name,
    messages=[
        {"role": "system", "content": planner_prompt},
        {"role": "user", "content": user_prompt}
    ],
    response_format={"type": "json_object"},
    temperature=0.0
)
t1 = time.time()
lat_on = round(t1 - t0, 2)
raw_on = res_on.choices[0].message.content or ""
plan_on = json.loads(repair_json_escapes(strip_fences(raw_on)))
print(f"[RUN 1 SUCCESS] Thinking ON Latency: {lat_on} seconds")

# ─── RUN 2: THINKING OFF ───
print("\n[RUN 2] Calling DeepSeek V4-Pro with Thinking OFF...")
t2 = time.time()
try:
    res_off = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": planner_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        extra_body={"thinking": {"type": "disabled"}}
    )
    t3 = time.time()
    lat_off = round(t3 - t2, 2)
    raw_off = res_off.choices[0].message.content or ""
    plan_off = json.loads(repair_json_escapes(strip_fences(raw_off)))
    print(f"[RUN 2 SUCCESS] Thinking OFF Latency: {lat_off} seconds")
except Exception as e:
    t3 = time.time()
    lat_off = round(t3 - t2, 2)
    print(f"[RUN 2 FAILED] Thinking OFF extra_body error: {e}")
    # Fallback attempt without extra_body
    plan_off = None

print("\n-------------------------------------------------------------------------")
print("LATENCY COMPARISON SUMMARY:")
print("-------------------------------------------------------------------------")
print(f"Thinking ON Latency : {lat_on} seconds")
if plan_off:
    print(f"Thinking OFF Latency: {lat_off} seconds")
    print(f"Speedup Factor      : {round(lat_on / lat_off, 2)}x faster!")
print("=========================================================================")

with open("scratch/plan_comparison.json", "w") as f:
    json.dump({
        "lat_on": lat_on,
        "lat_off": lat_off if plan_off else None,
        "plan_on": plan_on,
        "plan_off": plan_off
    }, f, indent=2)

print("\nSaved side-by-side plans to scratch/plan_comparison.json!")
