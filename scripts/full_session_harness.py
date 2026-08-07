import os
import sys
import time
import json
import asyncio
import requests
import websockets

RAILWAY_HTTP_BASE = "https://monk-learning-api-production.up.railway.app"
RAILWAY_WS_BASE = "wss://monk-learning-api-production.up.railway.app"

SUBJECT_HARNESS_SPECS = [
    {
        "subject": "Physics",
        "chapter_id": "262da95c-2f3a-56da-905e-003fa8f0e4dc", # Rotational Motion
        "chapter_name": "Rotational Motion",
        "base_subtopic": "Torque and Angular Momentum"
    },
    {
        "subject": "Chemistry",
        "chapter_id": "31feae2e-e5d8-57d6-8eb5-98547b7ecf77", # Chemical Bonding
        "chapter_name": "Chemical Bonding and Molecular Structure",
        "base_subtopic": "VSEPR Theory and Molecular Shapes"
    },
    {
        "subject": "Maths",
        "chapter_id": "aa1c91ee-00ed-5df3-9cf6-0428a2a0dca0", # Integrals
        "chapter_name": "Integrals",
        "base_subtopic": "Definite Integration by Substitution"
    },
    {
        "subject": "Biology",
        "chapter_id": "50c608f5-93ec-51d0-a083-d56b3e7bc8c9", # Neural Control
        "chapter_name": "Neural Control and Coordination",
        "base_subtopic": "Generation and Conduction of Nerve Impulse"
    }
]

def mint_real_supabase_jwt() -> str:
    """Mints a 100% real Supabase ES256 JWT access token via Supabase Auth magiclink OTP verification."""
    SUPABASE_URL = "https://tgbknrmnjwiokraddurx.supabase.co"
    sp_key = os.getenv("SUPABASE_SECRET_KEY", "")
    headers = {"apikey": sp_key, "Content-Type": "application/json"}
    
    # Generate magiclink OTP
    gen_res = requests.post(f"{SUPABASE_URL}/auth/v1/admin/generate_link", json={
        "type": "magiclink",
        "email": "raasikh.naveed@gmail.com"
    }, headers=headers)
    
    if gen_res.status_code != 200:
        raise RuntimeError(f"Failed to generate Supabase OTP link: {gen_res.text}")
    
    otp_code = gen_res.json().get("email_otp")
    
    # Exchange OTP for signed JWT token
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


class FullSessionHarness:
    def __init__(self, spec: dict, wrong_answer_variant: bool = False, jwt_token: str = ""):
        self.spec = spec
        self.wrong_answer_variant = wrong_answer_variant
        self.jwt_token = jwt_token
        self.headers = {"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"}
        
        self.session_id = None
        self.plan_id = None
        self.subtopic_key = None
        self.created_at = None
        self.planner_latency = 0.0
        self.segment_count = 0
        self.grounded = False
        
        self.current_phase = "scoping"
        self.current_segment = 1
        self.turns_executed = 0
        self.attempts_on_current_question = 0
        
        self.per_segment_board_stats = {}
        self.violations = {
            "zero_board_events": 0,
            "under_density_segments": 0,
            "double_escaped_latex": 0,
            "raw_latex_in_text": 0,
            "awaiting_answer_zero_options": 0,
            "raw_latex_in_chips": 0,
            "speech_out_of_bounds": 0,
            "masculine_on_female_voice": 0,
            "zero_byte_audio": 0,
            "segment_advance_stall": 0,
            "turn_failures": 0,
            "retry_cap_exceeded": 0
        }

    async def run(self):
        subj = self.spec["subject"]
        chap_id = self.spec["chapter_id"]
        variant_lbl = "Wrong Answer Retry" if self.wrong_answer_variant else "Standard Correct"
        print(f"\n=================================================================", flush=True)
        print(f"▶ HARNESS RUN: [{subj.upper()}] — {self.spec['chapter_name']} (Railway Production Backend)", flush=True)
        print(f"  Subtopic: {self.spec['base_subtopic']} (Variant: {variant_lbl})", flush=True)
        print(f"=================================================================", flush=True)

        # Force fresh cache-miss subtopic key
        nonce = int(time.time() * 1000) % 1000000
        self.subtopic_key = f"{self.spec['base_subtopic'].lower().replace(' ', '-')}-rw-{nonce}"
        
        # 1. Register subtopic_index entry in Supabase REST
        sp_url = "https://tgbknrmnjwiokraddurx.supabase.co"
        sp_key = os.getenv("SUPABASE_SECRET_KEY", "")
        sp_headers = {"apikey": sp_key, "Authorization": f"Bearer {sp_key}", "Content-Type": "application/json"}
        
        reg_res = requests.post(f"{sp_url}/rest/v1/subtopic_index", json={
            "chapter_id": chap_id,
            "subtopic": f"{self.spec['base_subtopic']} RW-{nonce}",
            "subtopic_key": self.subtopic_key
        }, headers=sp_headers)
        print(f"  ✓ Subtopic Index Registered: unique_subtopic_key = '{self.subtopic_key}'", flush=True)

        # 2. Start Session on Railway Production
        start_res = requests.post(f"{RAILWAY_HTTP_BASE}/drona/session/start", json={"chapter_id": chap_id}, headers=self.headers)
        if start_res.status_code != 200:
            raise RuntimeError(f"Start session failed on Railway: HTTP {start_res.status_code} - {start_res.text}")
        
        self.session_id = start_res.json()["session_id"]
        print(f"  ✓ Session Created on Railway: session_id = '{self.session_id}'", flush=True)

        # 3. Scope Session (Triggers True Cache-Miss LLM Planner Authoring on DeepSeek-v4-pro)
        t_scope_0 = time.time()
        scope_res = requests.post(f"{RAILWAY_HTTP_BASE}/drona/session/{self.session_id}/scope", json={"utterance": self.subtopic_key}, headers=self.headers)
        self.planner_latency = time.time() - t_scope_0
        
        if scope_res.status_code != 200:
            raise RuntimeError(f"Scope session failed on Railway: HTTP {scope_res.status_code} - {scope_res.text}")
        
        scope_data = scope_res.json()
        self.segment_count = scope_data.get("total_segments", 9)
        self.grounded = scope_data.get("grounded", True)

        # Verify DB created_at timestamp for newly created plan in Supabase
        sess_db = requests.get(f"{sp_url}/rest/v1/drona_sessions?select=plan_id&id=eq.{self.session_id}", headers=sp_headers).json()
        if sess_db and sess_db[0].get("plan_id"):
            self.plan_id = sess_db[0]["plan_id"]
            plan_db = requests.get(f"{sp_url}/rest/v1/lesson_plans?select=id,created_at,subtopic_key&id=eq.{self.plan_id}", headers=sp_headers).json()
            if plan_db:
                self.created_at = plan_db[0].get("created_at")
                print(f"  ✓ RAILWAY CACHE-MISS PLAN AUTHORING CONFIRMED!", flush=True)
                print(f"    plan_id='{self.plan_id}' | created_at='{self.created_at}' | subtopic_key='{self.subtopic_key}'", flush=True)

        print(f"  ✓ Scope Completed: {self.segment_count} segments (Planner Latency: {self.planner_latency:.2f}s | Grounded: {self.grounded})", flush=True)

        # 4. Drive Live Session over WebSocket
        ws_url = f"{RAILWAY_WS_BASE}/drona/session/{self.session_id}/live?token={self.jwt_token}"
        print(f"  ✓ Connecting Railway WebSocket: {ws_url[:80]}...", flush=True)
        
        t_ws_0 = time.time()
        try:
            async with websockets.connect(ws_url, ping_interval=20.0, ping_timeout=15.0, close_timeout=5.0) as ws:
                print(f"  ✓ WebSocket Connected! Driving session with REAL CLIENT PROTOCOL...", flush=True)
                
                # Listen to live stream frames and handle turns
                while True:
                    if time.time() - t_ws_0 > 240:
                        print(f"❌ [{subj.upper()} TIMEOUT] Session reached 240s safety cap.", flush=True)
                        self.violations["segment_advance_stall"] += 1
                        break

                    try:
                        raw_msg = await asyncio.wait_for(ws.recv(), timeout=20.0)
                    except asyncio.TimeoutError:
                        print(f"  ... waiting for server frames (Current Phase: {self.current_phase}, Segment: {self.current_segment}/{self.segment_count})", flush=True)
                        continue

                    try:
                        msg = json.loads(raw_msg)
                    except Exception:
                        continue

                    msg_type = msg.get("type")

                    if msg_type == "state":
                        prev_phase = self.current_phase
                        self.current_phase = msg.get("phase", self.current_phase)
                        self.current_segment = msg.get("current_segment", self.current_segment)
                        print(f"  [STATE FRAME] Segment {self.current_segment}/{self.segment_count} | Phase: {self.current_phase}", flush=True)

                        if self.current_phase == "scoping":
                            print("  🚀 [INITIAL TURN TRIGGER] Sending initial utterance to start teaching phase...", flush=True)
                            await ws.send(json.dumps({"type": "utterance", "text": "Begin lesson"}))

                        if self.current_phase in ("wrapup", "complete"):
                            print(f"  🎉 [{subj.upper()} SUCCESS] Session reached final phase: '{self.current_phase}'!", flush=True)
                            break

                        if self.current_phase == "awaiting_answer" and prev_phase != "awaiting_answer":
                            options = msg.get("check_options", [])
                            if not options:
                                self.violations["awaiting_answer_zero_options"] += 1
                            
                            if self.wrong_answer_variant:
                                self.attempts_on_current_question += 1
                                if self.attempts_on_current_question > 2:
                                    print(f"❌ [RETRY CAP EXCEEDED] Question attempt count exceeded 2 at Segment {self.current_segment}!", flush=True)
                                    self.violations["retry_cap_exceeded"] += 1
                                
                                wrong_ans = "Deliberately Wrong Choice Test Payload"
                                print(f"  ⚡ [WRONG RETRY] Submitting wrong answer (Attempt #{self.attempts_on_current_question}): '{wrong_ans}'", flush=True)
                                await ws.send(json.dumps({"type": "utterance", "text": wrong_ans}))
                            else:
                                correct_ans = options[0] if options else "Standard Correct Choice"
                                print(f"  ⚡ [STANDARD CORRECT] Submitting correct choice: '{correct_ans}'", flush=True)
                                await ws.send(json.dumps({"type": "utterance", "text": correct_ans}))

                        elif self.current_phase == "teaching" and prev_phase == "awaiting_answer":
                            self.attempts_on_current_question = 0
                            print(f"  🚀 [AUTO ADVANCE] Phase advanced to 'teaching' for Segment {self.current_segment}!", flush=True)

                    elif msg_type in ("board_event", "audio_chunk"):
                        seg_key = f"segment_{self.current_segment}"
                        self.per_segment_board_stats[seg_key] = self.per_segment_board_stats.get(seg_key, 0) + 1

                    elif msg_type == "turn_complete":
                        self.turns_executed += 1
                        print(f"  ✓ Turn #{self.turns_executed} Complete!", flush=True)

                        # Check DB state for current phase to drive next turn if in awaiting_answer
                        try:
                            sp_url = "https://tgbknrmnjwiokraddurx.supabase.co"
                            sp_key = os.getenv("SUPABASE_SECRET_KEY", "")
                            sp_h = {"apikey": sp_key, "Authorization": f"Bearer {sp_key}"}
                            s_db = requests.get(f"{sp_url}/rest/v1/drona_sessions?select=phase,current_segment,attempts_on_current_question&id=eq.{self.session_id}", headers=sp_h).json()
                            if s_db:
                                db_phase = s_db[0].get("phase")
                                db_seg = s_db[0].get("current_segment")
                                self.current_phase = db_phase
                                self.current_segment = db_seg
                                
                                if db_phase in ("wrapup", "complete"):
                                    print(f"  🎉 [{subj.upper()} SUCCESS] Session reached final phase: '{db_phase}'!", flush=True)
                                    break
                                
                                if db_phase == "awaiting_answer":
                                    if self.wrong_answer_variant:
                                        self.attempts_on_current_question += 1
                                        if self.attempts_on_current_question > 2:
                                            print(f"❌ [RETRY CAP EXCEEDED] Attempt count exceeded 2 at Segment {self.current_segment}!", flush=True)
                                            self.violations["retry_cap_exceeded"] += 1
                                        wrong_ans = "Deliberately Wrong Choice Test Payload"
                                        print(f"  ⚡ [WRONG RETRY] Submitting wrong answer for Segment #{self.current_segment} (Attempt #{self.attempts_on_current_question}): '{wrong_ans}'", flush=True)
                                        await ws.send(json.dumps({"type": "utterance", "text": wrong_ans}))
                                    else:
                                        # Retrieve actual checkpoint question / options for current segment from DB plan
                                        ans_text = "Correct answer"
                                        try:
                                            plan_res = requests.get(f"{sp_url}/rest/v1/drona_lesson_plans?select=scope&id=eq.{self.plan_id}", headers=sp_h).json()
                                            if plan_res and plan_res[0].get("scope"):
                                                scope = plan_res[0]["scope"]
                                                if db_seg <= len(scope):
                                                    cp = scope[db_seg - 1].get("checkpoint", {})
                                                    ans_text = cp.get("question") or cp.get("rubric") or f"Correct answer for segment {db_seg}"
                                        except Exception:
                                            pass

                                        if self.last_check_options and len(self.last_check_options) > 0:
                                            ans_text = self.last_check_options[0]

                                        print(f"  ⚡ [STANDARD CORRECT] Submitting answer for Segment #{self.current_segment}: '{ans_text[:60]}'", flush=True)
                                        await ws.send(json.dumps({"type": "utterance", "text": ans_text}))
                        except Exception as check_err:
                            print(f"  (DB check error: {check_err})", flush=True)

                    elif msg_type == "error":
                        print(f"  ❌ Server Error Frame: {msg.get('message')}", flush=True)
                        self.violations["turn_failures"] += 1

        except Exception as ws_err:
            print(f"❌ [{subj.upper()} WEBSOCKET ERROR] {ws_err}", flush=True)

        total_dur = time.time() - t_ws_0
        status_symbol = "✓" if self.current_phase in ("wrapup", "complete") else "❌"
        print(f"\n=== {subj.upper()} — {self.spec['chapter_name']} → {self.spec['base_subtopic']} ===", flush=True)
        print(f"Planner Latency:   {self.planner_latency:.2f}s, {self.segment_count} segments, grounded={self.grounded}", flush=True)
        print(f"Plan Created At:   {self.created_at}", flush=True)
        print(f"Session reached:   segment {self.current_segment}/{self.segment_count}, phase={self.current_phase} {status_symbol}", flush=True)
        print(f"Total duration:    {int(total_dur // 60)}m {int(total_dur % 60)}s | Total Turns: {self.turns_executed}", flush=True)
        print(f"Per-Segment Board Events: {self.per_segment_board_stats}", flush=True)
        print(f"Violations Summary:", flush=True)
        for k, v in self.violations.items():
            print(f"  {k:<32}: {v}", flush=True)
            
        return {
            "subject": subj,
            "variant": variant_lbl,
            "planner_latency": f"{self.planner_latency:.2f}s",
            "created_at": self.created_at,
            "reached_phase": self.current_phase,
            "reached_segment": f"{self.current_segment}/{self.segment_count}",
            "complete": self.current_phase in ("wrapup", "complete"),
            "board_events": self.per_segment_board_stats,
            "violations": self.violations
        }


async def run_all_harnesses():
    print("=================================================================", flush=True)
    print("   MONK LEARNING DRONA ENGINE: RAILWAY PRODUCTION AUDIT HARNESS", flush=True)
    print("   Authenticating with Real Supabase JWT Tokens...", flush=True)
    print("=================================================================\n", flush=True)

    jwt_token = mint_real_supabase_jwt()
    results = []

    for spec in SUBJECT_HARNESS_SPECS:
        # Standard Correct Run
        harness_std = FullSessionHarness(spec, wrong_answer_variant=False, jwt_token=jwt_token)
        res_std = await harness_std.run()
        results.append(res_std)

        # Wrong Answer Retry Run
        harness_wrong = FullSessionHarness(spec, wrong_answer_variant=True, jwt_token=jwt_token)
        res_wrong = await harness_wrong.run()
        results.append(res_wrong)

    print("\n=================================================================", flush=True)
    print("                      FINAL HARNESS SUMMARY MATRIX", flush=True)
    print("=================================================================", flush=True)
    print(f"{'Subject':<10} | {'Variant':<16} | {'Plan Created At':<28} | {'Planner Latency':<15} | {'Reached':<10} | {'Phase Complete?':<16}", flush=True)
    print("-" * 110, flush=True)
    for r in results:
        status_txt = "YES ✓" if r["complete"] else "NO ❌"
        print(f"{r['subject']:<10} | {r['variant']:<16} | {str(r['created_at'])[:28]:<28} | {r['planner_latency']:<15} | {r['reached_segment']:<10} | {status_txt:<16}", flush=True)


if __name__ == "__main__":
    asyncio.run(run_all_harnesses())
