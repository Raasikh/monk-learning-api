import os
import sys
import numpy as np
from dotenv import load_dotenv

load_dotenv('.env')
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.db import supabase

def generate_pilot_report():
    print("# DRONA PILOT PLATFORM TELEMETRY & CAPACITY REPORT", flush=True)
    print("-----------------------------------------------------------------", flush=True)

    # 1. Sessions Data
    sess_res = supabase.table("drona_sessions").select("*").execute()
    sessions = sess_res.data or []
    sess_count = len(sessions)

    completed_cnt = sum(1 for s in sessions if s.get("phase") in ("wrapup", "complete"))
    comp_rate = (completed_cnt / sess_count * 100.0) if sess_count > 0 else 0.0

    segs_list = [s.get("segments_completed", 0) for s in sessions if s.get("segments_completed") is not None]
    exhaust_list = [s.get("pool_exhaustion_count", 0) for s in sessions if s.get("pool_exhaustion_count") is not None]

    # Calculate session durations from turns
    turns_res = supabase.table("drona_turns").select("*").execute()
    turns = turns_res.data or []

    # 2. Rumik TTS Telemetry
    tot_rumik_req = sum(t.get("rumik_requests", 0) or 0 for t in turns)
    tot_rumik_chars = sum(t.get("rumik_chars", 0) or 0 for t in turns)
    
    plat_res = supabase.table("drona_platform_metrics").select("*").execute()
    plat_data = plat_res.data or []
    
    conns_open = [p.get("rumik_connections_open", 0) for p in plat_data]
    rpm_list = [p.get("rumik_requests_last_60s", 0) for p in plat_data]

    mean_rpm = float(np.mean(rpm_list)) if rpm_list else 0.0
    p99_rpm = float(np.percentile(rpm_list, 99)) if rpm_list else 0.0
    peak_conns = max(conns_open) if conns_open else 0

    # 3. Sarvam STT Telemetry
    tot_sarvam_req = len(turns)
    tot_stt_sec = tot_sarvam_req * 15.0  # ~15s audio per student turn

    # 4. LLM Tokens & Cost
    tot_input_tok = sum(t.get("input_tokens", 0) or 0 for t in turns)
    tot_cache_tok = sum(t.get("cache_hit_tokens", 0) or 0 for t in turns)
    tot_output_tok = sum(t.get("output_tokens", 0) or 0 for t in turns)

    cache_hit_rate = (tot_cache_tok / tot_input_tok * 100.0) if tot_input_tok > 0 else 0.0

    # Pricing (in INR ₹): DeepSeek $0.14/1M in, $0.28/1M out ($1 = ₹84)
    # Rumik TTS: ~₹0.04 / request
    # Sarvam STT: ~₹0.02 / request
    llm_cost_inr = ((tot_input_tok - tot_cache_tok) * 0.14 / 1e6 + tot_cache_tok * 0.014 / 1e6 + tot_output_tok * 0.28 / 1e6) * 84.0
    rumik_cost_inr = tot_rumik_req * 0.04
    sarvam_cost_inr = tot_sarvam_req * 0.02
    total_cost_inr = llm_cost_inr + rumik_cost_inr + sarvam_cost_inr
    cost_per_session_mean = (total_cost_inr / sess_count) if sess_count > 0 else 0.0

    # 5. Violations per Rule
    viol_counts = {}
    for t in turns:
        viols = t.get("violations") or {}
        for k, v in viols.items():
            viol_counts[k] = viol_counts.get(k, 0) + (1 if v else 0)

    # 6. Grade Distribution
    grade_dist = {}
    for t in turns:
        g = t.get("grade") or "N/A"
        grade_dist[g] = grade_dist.get(g, 0) + 1

    report_md = f"""# 📊 DRONA PILOT WEEKLY TELEMETRY & CAPACITY REPORT

### 1. Sessions Summary
- **Total Sessions**: `{sess_count}`
- **Completion Rate**: `{comp_rate:.1f}%` (`{completed_cnt}/{sess_count}`)
- **Mean Segments Completed**: `{np.mean(segs_list):.1f}` / 9
- **Pool Exhaustion Events**: `{sum(exhaust_list)}`

### 2. Rumik TTS Infrastructure Telemetry
- **Total Synthesis Requests**: `{tot_rumik_req}`
- **Total Characters Synthesized**: `{tot_rumik_chars:,}`
- **Mean Requests/Min**: `{mean_rpm:.1f}` RPM
- **p99 Requests/Min**: `{p99_rpm:.1f}` RPM
- **Peak Concurrent Connections**: `{peak_conns}` / 50 slots
- **Pool Exhaustions**: `{sum(exhaust_list)}`

### 3. Sarvam Saaras v3 STT Telemetry
- **Total STT Requests**: `{tot_sarvam_req}`
- **Total Audio Processed**: `{tot_stt_sec / 60.0:.1f} minutes` (`{tot_stt_sec:.0f} seconds`)

### 4. LLM Token Usage & Economics
- **Total Input Tokens**: `{tot_input_tok:,}`
- **Cache Hit Tokens**: `{tot_cache_tok:,}` (Cache Hit Rate: `{cache_hit_rate:.1f}%`)
- **Total Output Tokens**: `{tot_output_tok:,}`
- **Total Pilot Cost**: `₹{total_cost_inr:.2f}`
- **Mean Cost per Session**: `₹{cost_per_session_mean:.2f}`

### 5. Quality Rule Violations
| Rule | Violation Count | Rate per Turn |
|---|---|---|
"""
    for rule, cnt in viol_counts.items():
        rate = (cnt / len(turns) * 100.0) if turns else 0.0
        report_md += f"| `{rule}` | `{cnt}` | `{rate:.1f}%` |\n"

    report_md += f"""
### 6. Pedagogy & Misconceptions
- **Grade Distribution**: `{json.dumps(grade_dist)}`
"""

    print(report_md, flush=True)

if __name__ == "__main__":
    import json
    generate_pilot_report()
