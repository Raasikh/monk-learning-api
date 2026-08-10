"""
Full 3-segment test: forces session to advance between segments,
logs board events emitted per segment vs authored count.
"""
import asyncio
import json
import math
from dotenv import load_dotenv
load_dotenv('.env')
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.db import supabase
from app.drona.planner import get_or_create_plan
from app.drona.tutor import process_tutor_turn_stream

CHAPTER_ID = 'a88de5d2-84e4-5489-878a-f17a195e3267'
SUBTOPIC_KEY = 'conservative-and-non-conservative-forces'
USER_ID = '1c614fb1-0065-44d1-b5d8-f7583b453e08'

# Student responses for each turn (generic correct answers)
STUDENT_RESPONSES = {
    (1, 1): "Begin lesson segment",
    (1, 2): "Conservative force",
    (1, 3): "Conservative force saari energy wapas deti hai",
    (2, 1): "Begin segment 2",
    (2, 2): "Path pe depend nahi karta, sirf endpoints pe",
    (2, 3): "Zero hota hai closed loop mein",
    (3, 1): "Begin segment 3",
    (3, 2): "Jab sirf conservative forces kaam karein",
    (3, 3): "K plus U equals constant",
}

async def run_full_session():
    plan_row = get_or_create_plan(CHAPTER_ID, SUBTOPIC_KEY)
    plan_id = plan_row['id']
    plan_json = plan_row['plan_json']
    segments = plan_json['segments']
    total_segments = len(segments)

    print(f"Total segments in plan: {total_segments}")
    print()

    # Print authored board content per segment
    print("=" * 100)
    print("AUTHORED BOARD CONTENT PER SEGMENT")
    print("=" * 100)
    for i, seg in enumerate(segments, 1):
        bc = seg.get('board_content', [])
        n = len(bc) if isinstance(bc, list) else 0
        print(f"  Segment {i}: {n} authored items | Objective: {seg.get('objective', 'N/A')[:80]}")
    print()

    # Create session
    sess_res = supabase.table('drona_sessions').insert({
        'user_id': USER_ID,
        'mode': 'chapter',
        'chapter_id': CHAPTER_ID,
        'subtopic_key': SUBTOPIC_KEY,
        'language': 'hinglish',
        'plan_id': plan_id,
        'phase': 'teaching',
        'current_segment': 1,
        'attempts_on_current_question': 0,
        'history_summary': [],
        'grounded': True,
        'prompt_version': 'v1.0'
    }).execute()
    session_id = sess_res.data[0]['id']
    print(f"Created session: {session_id}")
    print()

    segment_results = []
    global_turn = 0

    for seg_idx in range(1, 4):  # Test first 3 segments
        seg = segments[seg_idx - 1]
        bc = seg.get('board_content', [])
        authored_count = len(bc) if isinstance(bc, list) else 0
        authored_texts = []
        if isinstance(bc, list):
            for item in bc:
                if isinstance(item, dict):
                    authored_texts.append(item.get('text') or item.get('latex', ''))
                else:
                    authored_texts.append(str(item))

        # FORCE session to correct segment BEFORE running turns
        supabase.table('drona_sessions').update({
            'current_segment': seg_idx,
            'phase': 'teaching',
            'attempts_on_current_question': 0
        }).eq('id', session_id).execute()
        print(f"==> Forced session to segment {seg_idx}")

        seg_board_events = []
        seg_turns = []

        for turn_in_seg in range(1, 4):  # 3 turns per segment
            global_turn += 1
            utterance = STUDENT_RESPONSES.get((seg_idx, turn_in_seg), "Continue")

            print(f"  [Seg {seg_idx} Turn {turn_in_seg}] Sending: \"{utterance[:60]}\"")

            async for sse in process_tutor_turn_stream(session_id, USER_ID, utterance, 'utterance'):
                pass

            # Fetch the turn
            turn_db = supabase.table('drona_turns').select('*').eq('session_id', session_id).eq('turn_index', global_turn).execute()
            if not turn_db.data:
                print(f"    WARNING: No turn found for turn_index={global_turn}")
                continue

            raw = turn_db.data[0].get('raw_response', {})
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except:
                    raw = {}

            board_events = raw.get('board_events', [])
            board_texts = [e.get('text') or e.get('latex', '') for e in board_events]
            seg_board_events.extend(board_texts)

            seg_turns.append({
                'turn': turn_in_seg,
                'board_count': len(board_events),
                'board_texts': board_texts,
                'phase_request': raw.get('phase_request'),
                'segment_complete': raw.get('segment_complete', False),
                'speech_preview': (raw.get('speech', '') or '')[:150]
            })

        segment_results.append({
            'segment': seg_idx,
            'objective': seg.get('objective', 'N/A'),
            'authored_count': authored_count,
            'authored_texts': authored_texts,
            'emitted_count': len(seg_board_events),
            'emitted_texts': seg_board_events,
            'turns': seg_turns
        })

    # Print the report
    print()
    print("=" * 120)
    print("                         FULL SEGMENT BOARD CONTENT AUDIT REPORT")
    print("=" * 120)

    for sr in segment_results:
        print(f"\n{'='*120}")
        print(f"SEGMENT {sr['segment']}: {sr['objective']}")
        print(f"  Authored board items: {sr['authored_count']}")
        print(f"  Emitted board items:  {sr['emitted_count']}")
        match = "✅ MATCH" if sr['emitted_count'] == sr['authored_count'] else f"❌ MISMATCH (delta: {sr['emitted_count'] - sr['authored_count']:+d})"
        print(f"  Status: {match}")
        print()

        print(f"  Authored items:")
        for i, t in enumerate(sr['authored_texts'], 1):
            txt = t if isinstance(t, str) else str(t)
            print(f"    [{i}] {txt[:90]}")

        print(f"\n  Emitted items:")
        for i, t in enumerate(sr['emitted_texts'], 1):
            print(f"    [{i}] {t[:90]}")

        # Check for cross-segment leakage
        print(f"\n  Turn breakdown:")
        for t in sr['turns']:
            print(f"    Turn {t['turn']}: {t['board_count']} board events | phase={t['phase_request']} | seg_complete={t['segment_complete']}")
            print(f"      speech: \"{t['speech_preview']}\"")
            for bt in t['board_texts']:
                print(f"      📝 {bt[:80]}")
        print("-" * 120)

    # Cross-segment leakage check
    print(f"\n{'='*120}")
    print("CROSS-SEGMENT LEAKAGE CHECK")
    print("=" * 120)
    for i, sr in enumerate(segment_results):
        if i + 1 < len(segment_results):
            next_sr = segment_results[i + 1]
            emitted_set = set(sr['emitted_texts'])
            next_authored_set = set(next_sr['authored_texts'])
            overlap = emitted_set & next_authored_set
            if overlap:
                print(f"  ❌ Segment {sr['segment']} emitted items that belong to Segment {next_sr['segment']}:")
                for o in overlap:
                    print(f"     - {o}")
            else:
                print(f"  ✅ Segment {sr['segment']} → Segment {next_sr['segment']}: No leakage detected")

    # Pacing distribution check
    print(f"\n{'='*120}")
    print("PACING DISTRIBUTION CHECK (Turn 1 should NOT dump all items)")
    print("=" * 120)
    for sr in segment_results:
        n = sr['authored_count']
        expected_t1 = math.ceil(n / 3)
        expected_t2 = math.ceil(n / 3)
        expected_t3 = n - expected_t1 - expected_t2
        actual_counts = [t['board_count'] for t in sr['turns']]
        expected_counts = [expected_t1, expected_t2, expected_t3]
        t1_dump = actual_counts[0] == n and n > 2
        print(f"  Segment {sr['segment']} (N={n}): expected={expected_counts}, actual={actual_counts} {'❌ TURN-1 DUMP' if t1_dump else '✅'}")

asyncio.run(run_full_session())
