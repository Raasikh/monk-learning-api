#!/usr/bin/env python3
"""
CLI script to dump readable session trace logs from Supabase DB for a given session_id.
Usage: python3 scripts/session_log.py <session_id>
"""
import sys
import json
import math
from dotenv import load_dotenv

load_dotenv('.env')
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.db import supabase

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/session_log.py <session_id>")
        sys.exit(1)

    session_id = sys.argv[1].strip()
    stag = f"[s:{session_id[:8]}]"

    # Fetch session
    sess_res = supabase.table("drona_sessions").select("*").eq("id", session_id).execute()
    if not sess_res.data:
        print(f"❌ Session '{session_id}' not found in database.")
        sys.exit(1)

    session = sess_res.data[0]
    plan_id = session.get("plan_id")

    # Fetch plan
    plan_json = {}
    if plan_id:
        plan_res = supabase.table("lesson_plans").select("plan_json").eq("id", plan_id).execute()
        if plan_res.data:
            plan_json = plan_res.data[0].get("plan_json", {})

    segments = plan_json.get("segments", [])
    total_segments = len(segments)

    # Fetch turns
    turns_res = supabase.table("drona_turns").select("*").eq("session_id", session_id).order("turn_index").execute()
    turns = turns_res.data or []

    print("=" * 100)
    print(f"SESSION TRACE REPORT — {session_id}")
    print("=" * 100)
    print(f"  Subtopic    : {session.get('subtopic_key')}")
    print(f"  Language    : {session.get('language')}")
    print(f"  Phase       : {session.get('phase')}")
    print(f"  Current Seg : {session.get('current_segment')} / {total_segments}")
    print(f"  Created At  : {session.get('created_at')}")
    print(f"  Total Turns : {len(turns)}")
    print("=" * 100)

    for t in turns:
        t_idx = t.get("turn_index", 1)
        seg_idx = t.get("segment_index", 1)
        phase_in = t.get("phase_in", "teaching")
        utterance = t.get("utterance")
        raw_resp = t.get("raw_response")

        parsed = {}
        if isinstance(raw_resp, str):
            try:
                parsed = json.loads(raw_resp)
            except Exception:
                parsed = {}
        elif isinstance(raw_resp, dict):
            parsed = raw_resp

        speech = parsed.get("speech", "")
        words = speech.split()
        word_cnt = len(words)
        board_events = parsed.get("board_events", [])
        board_cnt = len(board_events)
        p_req = parsed.get("phase_request")
        q_type = parsed.get("question_type")
        options = parsed.get("check_options") or []
        grade = t.get("grade") or parsed.get("grade")
        violations = t.get("violations") or {}
        v_list = [k for k, v in violations.items() if v]
        v_str = ", ".join(v_list) if v_list else "none"

        # Compute assigned board items for reference
        curr_seg = segments[seg_idx - 1] if seg_idx <= len(segments) else {}
        bc_raw = curr_seg.get("board_content", [])
        if isinstance(bc_raw, str):
            bc_list = [line.strip() for line in bc_raw.split("\n") if line.strip()]
        elif isinstance(bc_raw, list):
            bc_list = bc_raw
        else:
            bc_list = []

        N = len(bc_list)
        items_per_turn = math.ceil(N / 3) if N > 0 else 0
        
        # Estimate turn within segment
        turns_in_seg_so_far = [x for x in turns if x.get("segment_index") == seg_idx and x.get("turn_index") <= t_idx]
        turn_in_seg = len(turns_in_seg_so_far)

        if turn_in_seg == 1:
            a_start, a_end = 0, min(items_per_turn, N)
        elif turn_in_seg == 2:
            a_start, a_end = min(items_per_turn, N), min(2 * items_per_turn, N)
        else:
            a_start, a_end = min(2 * items_per_turn, N), N

        assigned_items = bc_list[a_start:a_end]
        assigned_texts = [x.get("text") or x.get("latex", "") if isinstance(x, dict) else str(x) for x in assigned_items]

        print(f"\n{stag} TURN {t_idx} START   seg={seg_idx}/{total_segments}  turn_in_seg={turn_in_seg}/3  phase={phase_in}")
        print(f"{stag}   STUDENT UTTERANCE : \"{utterance or ''}\"")
        print(f"{stag}   LLM               : in={t.get('input_tokens', 0)} cache={t.get('cache_hit_tokens', 0)} out={t.get('output_tokens', 0)}")
        print(f"{stag}   ASSIGNED          : {len(assigned_texts)} board items: {assigned_texts}")
        print(f"{stag}   EMITTED           : {board_cnt} board events  {'✓ matches assignment' if board_cnt == len(assigned_texts) else '❌ mismatch'}")
        print(f"{stag}   PHASE REQ         : phase_request={p_req} | question_type={q_type} | check_options={len(options)} {options}")
        if grade:
            print(f"{stag}   GRADE             : {grade}")
        print(f"{stag}   SPEECH            : ({word_cnt} words) \"{speech[:70]}...\"")
        for idx, b_evt in enumerate(board_events, 1):
            txt = b_evt.get("text") or b_evt.get("latex") or ""
            print(f"{stag}     📝 Event {idx}: [{b_evt.get('type')}] \"{txt}\"")
        print(f"{stag} TURN {t_idx} END     violations: {v_str}")
        print(f"{stag}   RAW JSON          : {json.dumps(parsed)}")

    print("\n" + "=" * 100)

if __name__ == "__main__":
    main()
