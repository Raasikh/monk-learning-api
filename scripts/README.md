# 🛠️ `scripts/` — Developer CLI & Diagnostic Tooling

The `scripts/` directory contains verified, official command-line tools for backend debugging, database telemetry inspection, session trace log reconstruction, and multi-segment test execution.

---

## 📂 Diagnostic Utilities

### 1. [`session_log.py`](file:///Users/raasikhnaveed/Desktop/monk-learning-api/scripts/session_log.py)
Reconstructs and prints a clean, readable execution trace for any session ID directly from `drona_turns` in Supabase DB:

```bash
PYTHONPATH=. python3 scripts/session_log.py <session_id>
```

> [!TIP]
> **Example Output**:
> ```text
> [s:15cbd4a6] TURN 1 START   seg=1/9  turn_in_seg=1/3  phase=teaching
> [s:15cbd4a6]   LLM          in=9359 cache=9344 out=404
> [s:15cbd4a6]   ASSIGNED     2 board items: ['Friction: force opposing...', '0 <= f_s <= mu_s N']
> [s:15cbd4a6]   EMITTED      2 board events  ✓ matches assignment
> [s:15cbd4a6]   PHASE REQ    phase_request=teaching | question_type=None | check_options=0
> [s:15cbd4a6]   SPEECH       (98 words) "Chalo, aaj hum friction ki kahani shuru karte hain..."
> [s:15cbd4a6] TURN 1 END     violations: none
> ```

---

### 2. [`drive_full_9_segments.py`](file:///Users/raasikhnaveed/Desktop/monk-learning-api/scripts/drive_full_9_segments.py)
Drives an end-to-end 9-segment live session over WebSockets, automatically answering Ask Sheet questions and advancing through all 9 segments:

```bash
PYTHONPATH=. python3 scripts/drive_full_9_segments.py
```

---

> [!NOTE]
> Standalone test scratchpads and temporary data dumps belong in `scratch/`, whereas production-ready diagnostic utilities are placed here in `scripts/`.
