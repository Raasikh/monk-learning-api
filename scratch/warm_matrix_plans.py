"""Regenerates the 4 matrix subtopics' plans up front, in parallel, so the
browser matrix measures UI/turn latency instead of one-off planner cost."""
import json, os, time
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
from app.drona.planner import get_or_create_plan, validate_plan_json

targets = json.load(open("/tmp/drona_matrix_targets.json"))

def warm(item):
    subj, v = item
    t0 = time.time()
    try:
        row = get_or_create_plan(v["chapter_id"], v["subtopic_key"])
        validate_plan_json(row["plan_json"])
        n = len(row["plan_json"]["segments"])
        b = sum(len(s.get("board_content", [])) for s in row["plan_json"]["segments"])
        return f"  {subj:<12} OK   {n} segments, {b} board items   ({time.time()-t0:.0f}s)"
    except Exception as e:
        return f"  {subj:<12} FAIL {str(e)[:110]}   ({time.time()-t0:.0f}s)"

with ThreadPoolExecutor(max_workers=4) as ex:
    for line in ex.map(warm, targets.items()):
        print(line, flush=True)
