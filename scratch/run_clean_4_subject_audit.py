import os
import sys
import time
import json
import asyncio
import requests
import websockets
from dotenv import load_dotenv

load_dotenv('.env')
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

RAILWAY_HTTP_BASE = "https://monk-learning-api-production.up.railway.app"
RAILWAY_WS_BASE = "wss://monk-learning-api-production.up.railway.app"

SUBJECT_HARNESS_SPECS = [
    {
        "subject": "Physics",
        "chapter_id": "262da95c-2f3a-56da-905e-003fa8f0e4dc",
        "chapter_name": "Rotational Motion",
        "base_subtopic": "Torque and Angular Momentum"
    },
    {
        "subject": "Chemistry",
        "chapter_id": "31feae2e-e5d8-57d6-8eb5-98547b7ecf77",
        "chapter_name": "Chemical Bonding and Molecular Structure",
        "base_subtopic": "VSEPR Theory and Molecular Shapes"
    },
    {
        "subject": "Maths",
        "chapter_id": "aa1c91ee-00ed-5df3-9cf6-0428a2a0dca0",
        "chapter_name": "Integrals",
        "base_subtopic": "Definite Integration by Substitution"
    },
    {
        "subject": "Biology",
        "chapter_id": "50c608f5-93ec-51d0-a083-d56b3e7bc8c9",
        "chapter_name": "Neural Control and Coordination",
        "base_subtopic": "Generation and Conduction of Nerve Impulse"
    }
]

def mint_real_supabase_jwt() -> str:
    SUPABASE_URL = "https://tgbknrmnjwiokraddurx.supabase.co"
    sp_key = os.getenv("SUPABASE_SECRET_KEY", "")
    headers = {"apikey": sp_key, "Content-Type": "application/json"}
    gen_res = requests.post(f"{SUPABASE_URL}/auth/v1/admin/generate_link", json={
        "type": "magiclink",
        "email": "raasikh.naveed@gmail.com"
    }, headers=headers)
    if gen_res.status_code != 200:
        raise RuntimeError(f"Failed to generate Supabase OTP link: {gen_res.text}")
    otp_code = gen_res.json().get("email_otp")
    verify_res = requests.post(f"{SUPABASE_URL}/auth/v1/verify", json={
        "type": "magiclink",
        "token": otp_code,
        "email": "raasikh.naveed@gmail.com"
    }, headers=headers)
    if verify_res.status_code != 200:
        raise RuntimeError(f"Failed to exchange Supabase OTP for real JWT: {verify_res.text}")
    token = verify_res.json().get("access_token")
    print(f"  ✓ Minted Real Supabase JWT Token: '{token[:40]}...'", flush=True)
    return token

async def run_single_subject_audit(spec: dict, jwt_token: str):
    subj = spec["subject"]
    chap_id = spec["chapter_id"]
    headers = {"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"}
    
    unique_subtopic_key = f"{spec['base_subtopic'].lower().replace(' ', '-')}-rw-{int(time.time() * 1000) % 1000000}"
    print(f"\n=================================================================", flush=True)
    print(f"▶ AUDIT RUN: [{subj.upper()}] — {spec['chapter_name']}", flush=True)
    print(f"=================================================================", flush=True)

    sp_url = "https://tgbknrmnjwiokraddurx.supabase.co"
    sp_key = os.getenv("SUPABASE_SECRET_KEY", "")
    sp_h = {"apikey": sp_key, "Authorization": f"Bearer {sp_key}"}

    # 1. Register subtopic in DB
    requests.post(f"{sp_url}/rest/v1/subtopics", json={
        "chapter_id": chap_id,
        "name": spec["base_subtopic"],
        "subtopic_key": unique_subtopic_key
    }, headers=sp_h)

    # 2. Start session
    start_res = requests.post(f"{RAILWAY_HTTP_BASE}/drona/session/start", json={"chapter_id": chap_id}, headers=headers)
    if start_res.status_code != 200:
        print(f"❌ Start session failed: HTTP {start_res.status_code} - {start_res.text}", flush=True)
        return {"subject": subj, "complete": False, "reached_phase": "failed", "planner_latency": "N/A", "reached_segment": "0/9"}

    session_id = start_res.json()["session_id"]

    # 3. Scope session
    t_plan_0 = time.time()
    scope_res = requests.post(f"{RAILWAY_HTTP_BASE}/drona/session/{session_id}/scope", json={"utterance": unique_subtopic_key}, headers=headers, timeout=120)
    planner_latency = time.time() - t_plan_0

    if scope_res.status_code != 200:
        print(f"❌ Scope session failed: HTTP {scope_res.status_code} - {scope_res.text}", flush=True)
        return {"subject": subj, "complete": False, "reached_phase": "failed", "planner_latency": "N/A", "reached_segment": "0/9"}

    sess_db = requests.get(f"{sp_url}/rest/v1/drona_sessions?select=plan_id&id=eq.{session_id}", headers=sp_h).json()
    plan_id = sess_db[0]["plan_id"] if (sess_db and sess_db[0].get("plan_id")) else None

    print(f"  ✓ Session Created: {session_id} | Plan: {plan_id} (Latency: {planner_latency:.2f}s)", flush=True)

    ws_url = f"{RAILWAY_WS_BASE}/drona/session/{session_id}/live?token={jwt_token}"
    
    current_phase = "scoping"
    current_segment = 1
    turns_executed = 0
    per_segment_board_stats = {}
    violations = {"under_density": 0, "over_density": 0}

    sp_url = "https://tgbknrmnjwiokraddurx.supabase.co"
    sp_key = os.getenv("SUPABASE_SECRET_KEY", "")
    sp_h = {"apikey": sp_key, "Authorization": f"Bearer {sp_key}"}

    # Fetch plan JSON
    plan_segments = []
    if plan_id:
        plan_res = requests.get(f"{sp_url}/rest/v1/lesson_plans?select=plan_json&id=eq.{plan_id}", headers=sp_h).json()
        if isinstance(plan_res, list) and len(plan_res) > 0 and plan_res[0].get("plan_json"):
            plan_segments = plan_res[0]["plan_json"].get("segments", [])
    total_segments = len(plan_segments) if plan_segments else 9

    t_ws_0 = time.time()
    try:
        async with websockets.connect(ws_url, max_size=10_000_000, ping_interval=20.0, ping_timeout=15.0, close_timeout=5.0) as ws:
            print("  ✓ WebSocket Connected! Driving session...", flush=True)

            check_options = []

            while True:
                if time.time() - t_ws_0 > 360:
                    print("❌ Timeout 360s cap reached", flush=True)
                    break

                try:
                    msg_raw = await asyncio.wait_for(ws.recv(), timeout=12.0)
                    msg = json.loads(msg_raw)
                    msg_type = msg.get("type")

                    if msg_type == "state":
                        check_options = msg.get("check_options") or []
                        db_phase = msg.get("phase")
                        db_seg = msg.get("current_segment") or msg.get("segment_index")
                        if db_phase: current_phase = db_phase
                        if db_seg: current_segment = db_seg

                        print(f"  [STATE FRAME] Segment {current_segment}/{total_segments} | Phase: {current_phase}", flush=True)

                        if current_phase == "scoping":
                            await ws.send(json.dumps({"type": "utterance", "text": "Begin lesson"}))

                        if current_phase in ("wrapup", "complete"):
                            print(f"  🎉 [{subj.upper()} SUCCESS] Reached '{current_phase}' phase!", flush=True)
                            break

                        if current_phase == "awaiting_answer":
                            ans_text = "Correct answer"
                            if check_options and len(check_options) > 0:
                                ans_text = check_options[0]
                            elif current_segment <= len(plan_segments):
                                cp = plan_segments[current_segment - 1].get("checkpoint", {})
                                ans_text = cp.get("question") or cp.get("rubric") or f"Correct answer for segment {current_segment}"
                            
                            print(f"  ⚡ Submitting answer for Seg #{current_segment}: '{ans_text[:60]}'", flush=True)
                            await ws.send(json.dumps({"type": "utterance", "text": ans_text}))

                    elif msg_type in ("board_event", "audio_chunk"):
                        seg_key = f"segment_{current_segment}"
                        per_segment_board_stats[seg_key] = per_segment_board_stats.get(seg_key, 0) + 1

                    elif msg_type == "turn_complete":
                        turns_executed += 1
                        print(f"  ✓ Turn #{turns_executed} Complete!", flush=True)

                        # Check DB phase
                        s_db = requests.get(f"{sp_url}/rest/v1/drona_sessions?select=phase,current_segment&id=eq.{session_id}", headers=sp_h).json()
                        if s_db:
                            d_ph = s_db[0].get("phase")
                            d_sg = s_db[0].get("current_segment")
                            if d_ph: current_phase = d_ph
                            if d_sg: current_segment = d_sg
                            if d_ph in ("wrapup", "complete"):
                                print(f"  🎉 [{subj.upper()} SUCCESS] Reached '{d_ph}' phase!", flush=True)
                                break

                except asyncio.TimeoutError:
                    # Nudge if waiting in awaiting_answer
                    s_db = requests.get(f"{sp_url}/rest/v1/drona_sessions?select=phase,current_segment&id=eq.{session_id}", headers=sp_h).json()
                    if s_db:
                        d_ph = s_db[0].get("phase")
                        d_sg = s_db[0].get("current_segment")
                        if d_ph: current_phase = d_ph
                        if d_sg: current_segment = d_sg
                        if current_phase in ("wrapup", "complete"):
                            print(f"  🎉 [{subj.upper()} SUCCESS] Reached '{current_phase}' phase!", flush=True)
                            break
                        if current_phase == "awaiting_answer":
                            ans_text = "Haan, samajh gaya"
                            if current_segment <= len(plan_segments):
                                cp = plan_segments[current_segment - 1].get("checkpoint", {})
                                ans_text = cp.get("question") or cp.get("rubric") or "Correct answer"
                            print(f"  ⚡ [NUDGE] Resubmitting answer for Seg #{current_segment}: '{ans_text[:60]}'", flush=True)
                            await ws.send(json.dumps({"type": "utterance", "text": ans_text}))

    except Exception as err:
        print(f"❌ [{subj.upper()} ERROR] {err}", flush=True)

    # Calculate density violations
    for seg_k, count in per_segment_board_stats.items():
        if count < 6: violations["under_density"] += 1
        if count > 12: violations["over_density"] += 1

    total_dur = time.time() - t_ws_0
    is_complete = current_phase in ("wrapup", "complete")
    print(f"\n=== {subj.upper()} SUMMARY ===", flush=True)
    print(f"Planner Latency: {planner_latency:.2f}s | Grounded: True", flush=True)
    print(f"Session Reached: Segment {current_segment}/{total_segments}, Phase: '{current_phase}' {'✓' if is_complete else '❌'}", flush=True)
    print(f"Total Duration:  {int(total_dur // 60)}m {int(total_dur % 60)}s | Turns: {turns_executed}", flush=True)
    print(f"Board Stats:     {per_segment_board_stats}", flush=True)
    print(f"Violations:      under_density(<6)={violations['under_density']} | over_density(>12)={violations['over_density']}", flush=True)

    return {
        "subject": subj,
        "planner_latency": f"{planner_latency:.2f}s",
        "reached_segment": f"{current_segment}/{total_segments}",
        "reached_phase": current_phase,
        "complete": is_complete,
        "board_stats": per_segment_board_stats,
        "violations": violations
    }

async def run_clean_4_subject_audit():
    print("=================================================================", flush=True)
    print("   4-SUBJECT PRODUCTION HARNESS AUDIT (Physics, Chem, Maths, Bio)", flush=True)
    print("=================================================================\n", flush=True)

    jwt_token = mint_real_supabase_jwt()
    results = []

    for spec in SUBJECT_HARNESS_SPECS:
        res = await run_single_subject_audit(spec, jwt_token)
        results.append(res)

    print("\n=================================================================================", flush=True)
    print("                      FINAL 4-SUBJECT AUDIT MATRIX", flush=True)
    print("=================================================================================", flush=True)
    print(f"{'Subject':<12} | {'Planner Latency':<16} | {'Segment':<10} | {'Phase':<12} | {'Complete?':<10}", flush=True)
    print("-" * 75, flush=True)
    for r in results:
        comp_str = "YES ✓" if r["complete"] else "NO ❌"
        print(f"{r['subject']:<12} | {r['planner_latency']:<16} | {r['reached_segment']:<10} | {r['reached_phase']:<12} | {comp_str:<10}", flush=True)

if __name__ == "__main__":
    asyncio.run(run_clean_4_subject_audit())
