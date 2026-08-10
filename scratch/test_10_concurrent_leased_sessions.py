import os
import time
import asyncio
import random
from dotenv import load_dotenv

load_dotenv('.env')
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.drona.voice_proxy import RumikConnectionPool, RumikTTSProxy

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

async def simulate_student_session(session_index: int):
    session_id = f"test_sim_session_{session_index}_{int(time.time())}"
    proxy = RumikTTSProxy(voice_preset="Ira", model="mulberry", session_id=session_id)
    
    turns_count = 5
    zero_bytes_count = 0
    gaps_count = 0

    print(f"  ▶ [STUDENT #{session_index}] Starting simulated teaching session...", flush=True)

    for turn in range(1, turns_count + 1):
        sentences = [
            f"Namaste! Turn #{turn} sentence 1 concept explanation for student {session_index}.",
            f"Here is sentence 2 with mathematical formula and worked example for student {session_index}.",
            f"Aap batayein kya yeh topic aapko achhi tarah clear hua student {session_index}?"
        ]

        t_turn_start = time.time()
        for sentence in sentences:
            pcm_bytes = await proxy.synthesize_text(sentence)
            if len(pcm_bytes) == 0:
                zero_bytes_count += 1
            # Check for unusual gap (>3.0s)
            ttfb = time.time() - t_turn_start
            if ttfb > 4.0:
                gaps_count += 1

        # Student listening & thinking pause: 15s speech in 45s cycle (~30s student pause)
        # 4s grace period timer on connection lease automatically fires if pause > 4.0s!
        await asyncio.sleep(random.uniform(5.0, 7.0))

    print(f"  ✓ [STUDENT #{session_index}] Session complete across {turns_count} turns.", flush=True)
    return {
        "session_id": session_id,
        "zero_bytes": zero_bytes_count,
        "audible_gaps": gaps_count
    }

async def run_10_concurrent_harness():
    print("=================================================================", flush=True)
    print(" 🚀 RUNNING 10 CONCURRENT SIMULATED SESSIONS ON RUMIK POOL      ", flush=True)
    print("=================================================================\n", flush=True)

    pool = RumikConnectionPool.get_instance()
    
    # Launch 10 simulated student sessions concurrently
    tasks = [simulate_student_session(i) for i in range(1, 11)]
    results = await asyncio.gather(*tasks)

    # Compute metrics
    peak_conns = max(pool.concurrent_held_history) if pool.concurrent_held_history else 0
    total_exhaustions = pool.pool_exhaustion_count
    total_zero_bytes = sum(r["zero_bytes"] for r in results)
    total_gaps = sum(r["audible_gaps"] for r in results)

    print("\n=================================================================", flush=True)
    print("        10-CONCURRENT LEASED POOL AUDIT VERIFICATION RESULTS      ", flush=True)
    print("=================================================================", flush=True)
    print(f"  Peak Concurrent Connections Held : {peak_conns} / 50 slots", flush=True)
    print(f"  Pool Exhaustion Events           : {total_exhaustions}", flush=True)
    print(f"  Zero-Byte Audio Failures         : {total_zero_bytes}", flush=True)
    print(f"  Audible Gap Violations (>4s)    : {total_gaps}", flush=True)
    print("=================================================================", flush=True)

if __name__ == "__main__":
    asyncio.run(run_10_concurrent_harness())
