"""End-to-end session drive over the real WebSocket path.

Per AGENTS.md Rule 2 every assertion prints its own line — a single PASSED at
the end is not useful when something breaks at segment 6.

Exercises the changes from this round:
  - tutor_voice -> Rumik preset + tutor_gender (migration 0011)
  - session language -> speech, chips, server-authored copy
  - lease release at turn end / on disconnect
  - phase written to DB matches phase sent to client (guardrail ordering)
  - checkpoint question delivered as a silent caption
  - board events present, balanced LaTeX, no cross-segment leakage

Run with the local server up on :8000 and .env exported.
"""
import asyncio
import json
import os
import re
import sys
import time
from collections import defaultdict

import websockets
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.db import supabase  # noqa: E402

WS_BASE = os.getenv("E2E_WS_BASE", "ws://localhost:8000")
MAX_TURNS = int(os.getenv("E2E_MAX_TURNS", "40"))
TURN_TIMEOUT = 120.0

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
HINDI_FILLERS = re.compile(
    r"\b(dekho|samajh|chalo|theek hai|bilkul|achha|arre|haan|bhai|yaar|karte hain|"
    r"batao|sahi|aage badh|ek baar|thoda|kya|hai na|toh)\b",
    re.IGNORECASE,
)

results = []


def check(label, ok, detail=""):
    results.append((label, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""), flush=True)
    return ok


def latex_balanced(s: str) -> bool:
    return s.count("{") == s.count("}") and s.count("$") % 2 == 0


def pick_cached_plan():
    """A plan already in lesson_plans — avoids a planner LLM call and any embedding."""
    rows = supabase.table("lesson_plans").select("id, chapter_id, subtopic_key, plan_json, segment_count").execute().data or []
    for r in rows:
        pj = r.get("plan_json") or {}
        segs = pj.get("segments") or []
        if len(segs) >= 6 and all(isinstance(s.get("board_content"), list) for s in segs):
            return r
    return None


def make_session(user_id, plan, voice, language):
    row = supabase.table("drona_sessions").insert([{
        "user_id": user_id,
        "chapter_id": plan["chapter_id"],
        "subtopic_key": plan["subtopic_key"],
        "mode": "chapter",
        "language": language,
        "tutor_voice": voice,
        "plan_id": plan["id"],
        "phase": "teaching",
        "current_segment": 1,
        "prompt_version": "e2e-persona-lang",
    }]).execute()
    return row.data[0]["id"]


async def drive(session_id, language, voice, total_segments, label):
    print(f"\n{'='*78}\n  {label}  (voice={voice}, language={language}, session={session_id[:8]})\n{'='*78}", flush=True)

    uri = f"{WS_BASE}/drona/session/{session_id}/live"
    stats = {
        "audio_chunks": 0, "silent_captions": 0, "board_events": 0,
        "turns": 0, "errors": [], "speech": [], "segments_seen": set(),
        "chips": [], "handshake": None, "board_by_seg": defaultdict(list),
        "unbalanced": [],
    }
    current_segment = 1
    pending_options = []

    async with websockets.connect(uri, max_size=None, ping_interval=None) as ws:
        stats["handshake"] = json.loads(await ws.recv())

        deadline = time.time() + 900
        while stats["turns"] < MAX_TURNS and time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=TURN_TIMEOUT)
            except asyncio.TimeoutError:
                stats["errors"].append("ws recv timeout")
                break
            if not isinstance(raw, str):
                continue
            msg = json.loads(raw)
            t = msg.get("type")

            if t == "audio_chunk":
                if msg.get("audio"):
                    stats["audio_chunks"] += 1
                else:
                    stats["silent_captions"] += 1
                if msg.get("speech"):
                    stats["speech"].append(msg["speech"])
            elif t == "board_events":
                evts = msg.get("events") or []
                stats["board_events"] += len(evts)
                for e in evts:
                    content = e.get("latex") or e.get("text") or ""
                    stats["board_by_seg"][current_segment].append(content)
                    if e.get("type") == "formula" and not latex_balanced(content):
                        stats["unbalanced"].append(content)
            elif t == "meta":
                if msg.get("segment_index"):
                    current_segment = msg["segment_index"]
                    stats["segments_seen"].add(current_segment)
            elif t == "state":
                opts = msg.get("check_options") or []
                if opts:
                    pending_options = opts
                    stats["chips"].append(opts)
                if msg.get("phase") == "complete":
                    print("  · session reached phase=complete", flush=True)
                    break
            elif t == "error":
                stats["errors"].append(msg.get("message"))
                print(f"  · server error frame: {msg.get('message')}", flush=True)
            elif t == "turn_complete":
                stats["turns"] += 1
                db = supabase.table("drona_sessions").select("phase, current_segment").eq("id", session_id).single().execute().data
                print(f"  · turn {stats['turns']:>2} done | db_phase={db['phase']:<16} db_seg={db['current_segment']} "
                      f"| audio={stats['audio_chunks']} board={stats['board_events']}", flush=True)
                if db["phase"] == "awaiting_answer":
                    answer = pending_options[0] if pending_options else "Yes"
                    pending_options = []
                    await asyncio.sleep(0.4)
                    await ws.send(json.dumps({"type": "utterance", "text": answer}))
                elif db["phase"] in ("complete", "wrapup"):
                    break

    return stats


def assert_session(stats, language, voice, expected_name, total_segments):
    hs = stats["handshake"] or {}
    check("WS handshake returns the selected persona",
          hs.get("tutor_name") == expected_name, f"tutor_name={hs.get('tutor_name')!r}")
    check("WS handshake returns the selected language",
          hs.get("language") == language, f"language={hs.get('language')!r}")
    check("Audio frames were produced", stats["audio_chunks"] > 0, f"{stats['audio_chunks']} chunks")
    check("Board events were produced", stats["board_events"] > 0, f"{stats['board_events']} events")
    check("No server error frames", not stats["errors"], "; ".join(map(str, stats["errors"][:3])))
    check("All formula LaTeX balanced", not stats["unbalanced"],
          f"{len(stats['unbalanced'])} unbalanced: {stats['unbalanced'][:2]}")
    check("Checkpoint questions delivered silently", stats["silent_captions"] > 0,
          f"{stats['silent_captions']} silent captions")
    check("Every question carried option chips", all(len(c) >= 2 for c in stats["chips"]),
          f"{len(stats['chips'])} chip sets, sizes={[len(c) for c in stats['chips']][:8]}")
    check("Session advanced past segment 1", max(stats["segments_seen"] or {1}) > 1,
          f"segments reached: {sorted(stats['segments_seen'])}")

    joined = " ".join(stats["speech"])
    check("No Devanagari in speech", not DEVANAGARI.search(joined))
    if language == "english":
        hits = sorted(set(m.group(0).lower() for m in HINDI_FILLERS.finditer(joined)))
        check("English session contains no Hindi/Hinglish words", not hits, f"found: {hits[:8]}")
        chip_hits = [c for cs in stats["chips"] for c in cs if HINDI_FILLERS.search(c)]
        check("English session chips are English", not chip_hits, f"found: {chip_hits[:4]}")

    # Cross-segment leakage: a board line authored for one segment must not
    # reappear under another.
    seen = {}
    leaks = []
    for seg, items in stats["board_by_seg"].items():
        for it in items:
            k = (it or "").strip().lower()
            if not k:
                continue
            if k in seen and seen[k] != seg:
                leaks.append((k[:40], seen[k], seg))
            seen[k] = seg
    check("No board content repeated across segments", not leaks, f"{len(leaks)} leaks: {leaks[:2]}")


async def main():
    plan = pick_cached_plan()
    if not plan:
        sys.exit("No cached list-shaped plan found in lesson_plans; cannot run without a planner call.")
    segs = plan["plan_json"]["segments"]
    print(f"Using cached plan {plan['id'][:8]} subtopic={plan['subtopic_key']} segments={len(segs)}", flush=True)

    user_id = (supabase.table("profiles").select("id").limit(1).execute().data or [{}])[0].get("id")
    if not user_id:
        sys.exit("No profiles row to own the test session.")

    for voice, language, name, label in [
        ("female", "hinglish", "Veda", "SESSION A — Veda / Hinglish (full run)"),
        ("male", "english", "Drona", "SESSION B — Drona / English (full run)"),
    ]:
        sid = make_session(user_id, plan, voice, language)
        stats = await drive(sid, language, voice, len(segs), label)
        print(f"\n  --- assertions: {label} ---", flush=True)
        assert_session(stats, language, voice, name, len(segs))

    print(f"\n{'='*78}")
    failed = [l for l, ok in results if not ok]
    print(f"  {len(results) - len(failed)}/{len(results)} assertions passed")
    if failed:
        print("  FAILED:")
        for f in failed:
            print(f"    - {f}")
    print(f"{'='*78}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
