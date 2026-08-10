"""Reproduces the biology planner failure and reports WHY the JSON is invalid.

finish_reason == "length" proves truncation (output cap hit) — fix is a bigger
budget or a smaller payload. Anything else means the content itself is
malformed, which points at an unescaped quote or backslash inside a string.
The two have completely different fixes, so measure rather than guess.
"""
import json
import os
import time

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.db import supabase  # noqa: E402
from app.drona.models import get_drona_client, get_model_name, PLANNER_TIMEOUT_S  # noqa: E402
from app.drona.prompt_loader import load_prompt  # noqa: E402
from app.drona.retrieval import retrieve_dual_blocks  # noqa: E402

t = json.load(open("/tmp/drona_matrix_targets.json"))["biology"]
chap = supabase.table("chapters").select("name,subject").eq("id", t["chapter_id"]).execute().data[0]
structure, depth, _ = retrieve_dual_blocks(t["chapter_id"], t["subtopic"])

user = f"""
Chapter: {chap['name']} ({chap['subject']})
Subtopic: {t['subtopic']} (Key: {t['subtopic_key']})

{structure}

{depth}

Author a complete lesson plan JSON following the instructions in the system prompt.
"""

client = get_drona_client()
model = get_model_name("planner")
t0 = time.time()
res = client.chat.completions.create(
    model=model,
    messages=[{"role": "system", "content": load_prompt("planner.md")},
              {"role": "user", "content": user}],
    response_format={"type": "json_object"},
    temperature=0.0,
    max_tokens=16384,
    timeout=PLANNER_TIMEOUT_S,
    extra_body={"thinking": {"type": "disabled"}},
)

content = res.choices[0].message.content or ""
fr = getattr(res.choices[0], "finish_reason", None)
u = getattr(res, "usage", None)

print(f"finish_reason : {fr}")
print(f"output_tokens : {getattr(u, 'completion_tokens', None)}")
print(f"chars         : {len(content)}   ({time.time()-t0:.0f}s)")

try:
    parsed = json.loads(content)
    print("parses        : YES")
    segs = parsed.get("segments", [])
    print(f"segments      : {len(segs)}")
    print(f"board items   : {[len(s.get('board_content', [])) for s in segs]}")
    from app.drona.planner import validate_plan_json
    try:
        validate_plan_json(parsed)
        print("validates     : YES")
    except Exception as ve:
        print(f"validates     : NO -> {ve}")
except Exception as e:
    print(f"parses        : NO  -> {e}")
    pos = getattr(e, "pos", None)
    if pos:
        print(f"context around offset {pos}:")
        print(f"  ...{content[max(0,pos-120):pos]!r}")
        print(f"  >>> {content[pos:pos+1]!r} <<<")
        print(f"  {content[pos+1:pos+120]!r}...")
    print(f"tail (last 120 chars): ...{content[-120:]!r}")
    if fr == "length":
        print("\nVERDICT: TRUNCATION — the model hit the output cap mid-object.")
    else:
        print("\nVERDICT: MALFORMED CONTENT — not truncation. Most likely an "
              "unescaped double quote or backslash inside a string value.")
