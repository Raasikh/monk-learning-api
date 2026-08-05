import os
import time
import json
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.db import supabase
from app.drona.retrieval import retrieve_dual_blocks
from app.drona.prompt_loader import load_prompt, get_prompt_version
from app.drona.models import get_drona_client, get_model_name
from app.drona.planner import strip_fences, repair_json_escapes, validate_plan_json

print("=========================================================================")
print("PER-STAGE TIMING BREAKDOWN BENCHMARK (create_plan_with_llm)")
print("=========================================================================")

chap_res = supabase.table("chapters").select("id, name, subject").limit(1).execute()
chap = chap_res.data[0]
chapter_id = chap["id"]
subtopic_key = f"benchmark-subtopic-{int(time.time())}"
sub_title = "First Law of Thermodynamics & Internal Energy"

# ─── STAGE 1: RETRIEVAL ───
t_ret_start = time.time()
structure_block, depth_block, is_grounded = retrieve_dual_blocks(chapter_id, sub_title)
t_ret_end = time.time()
retrieval_ms = round((t_ret_end - t_ret_start) * 1000, 2)

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

# ─── STAGE 2: LLM COMPLETION (DEEPSEEK V4-PRO) ───
t_llm_start = time.time()
res = client.chat.completions.create(
    model=model_name,
    messages=[
        {"role": "system", "content": planner_prompt},
        {"role": "user", "content": user_prompt}
    ],
    response_format={"type": "json_object"},
    temperature=0.0
)
t_llm_end = time.time()
llm_latency_s = round(t_llm_end - t_llm_start, 2)

raw_content = res.choices[0].message.content or ""

# ─── STAGE 3: VALIDATION & DB INSERT ───
t_val_start = time.time()
cleaned = strip_fences(raw_content)
repaired = repair_json_escapes(cleaned)
plan_json = json.loads(repaired)
validate_plan_json(plan_json)

segment_count = len(plan_json["segments"])
prompt_ver = get_prompt_version()

ins_res = supabase.table("lesson_plans").insert([{
    "chapter_id": chapter_id,
    "subtopic_key": subtopic_key,
    "plan_json": plan_json,
    "grounded": is_grounded,
    "segment_count": segment_count,
    "source_model": model_name,
    "prompt_version": prompt_ver
}]).execute()
t_val_end = time.time()
val_ms = round((t_val_end - t_val_start) * 1000, 2)

total_latency_s = round(t_val_end - t_ret_start, 2)

print("\n-------------------------------------------------------------------------")
print("PER-STAGE TIMINGS FOR DEEPSEEK PLANNER (THINKING ON):")
print("-------------------------------------------------------------------------")
print(f"1. Retrieval Stage (Embeddings + RAG blocks): {retrieval_ms} ms ({round(retrieval_ms/1000, 2)} s)")
print(f"2. DeepSeek V4-Pro LLM Completion Call: {llm_latency_s} seconds ({(llm_latency_s/total_latency_s)*100:.1f}% of total)")
print(f"3. Validation & DB Insert Stage: {val_ms} ms ({round(val_ms/1000, 2)} s)")
print("-------------------------------------------------------------------------")
print(f"TOTAL END-TO-END LATENCY: {total_latency_s} seconds")
print("=========================================================================")
