import re
import json
from typing import Dict, List
from app.db import supabase

def make_subtopic_key(subtopic: str) -> str:
    """Creates a lowercase, normalized slug for subtopic_key."""
    s = subtopic.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')

def backfill_subtopic_index():
    print("Fetching all lesson_sections from Supabase...")
    
    # 1. Fetch all lesson_sections
    all_sections = []
    offset = 0
    limit = 1000
    while True:
        res = supabase.table('lesson_sections').select('chapter_id, subtopic').range(offset, offset + limit - 1).execute()
        if not res.data:
            break
        all_sections.extend(res.data)
        offset += limit
        if len(res.data) < limit:
            break

    print(f"Fetched {len(all_sections)} total lesson_sections.")

    # 2. Fetch all chapters for subject reporting
    all_chapters = []
    offset = 0
    while True:
        res = supabase.table('chapters').select('id, subject, name').range(offset, offset + limit - 1).execute()
        if not res.data:
            break
        all_chapters.extend(res.data)
        offset += limit
        if len(res.data) < limit:
            break

    chapter_subject_map = {c['id']: (c.get('subject') or 'unknown').lower() for c in all_chapters}

    # 3. Group by (chapter_id, subtopic_key)
    grouped: Dict[tuple, dict] = {}

    for row in all_sections:
        cid = row.get('chapter_id')
        sub = (row.get('subtopic') or '').strip()
        if not cid or not sub:
            continue

        key = make_subtopic_key(sub)
        if not key:
            continue

        pair = (cid, key)
        if pair not in grouped:
            grouped[pair] = {
                'chapter_id': cid,
                'subtopic': sub,
                'subtopic_key': key,
                'section_count': 0,
                'subject': chapter_subject_map.get(cid, 'unknown')
            }
        grouped[pair]['section_count'] += 1

    subtopic_rows = list(grouped.values())
    print(f"Compiled {len(subtopic_rows)} unique (chapter_id, subtopic_key) index records.")

    # 4. Upsert into subtopic_index table in Supabase
    chunk_size = 200
    upserted_count = 0
    for i in range(0, len(subtopic_rows), chunk_size):
        chunk = subtopic_rows[i:i + chunk_size]
        # Remove subject key before insert (not in table schema)
        db_chunk = [{
            'chapter_id': r['chapter_id'],
            'subtopic': r['subtopic'],
            'subtopic_key': r['subtopic_key'],
            'section_count': r['section_count']
        } for r in chunk]

        res = supabase.table('subtopic_index').upsert(db_chunk, on_conflict='chapter_id,subtopic_key').execute()
        upserted_count += len(res.data or [])

    print(f"Successfully upserted {upserted_count} subtopic_index rows into Supabase!")

    # 5. Report total count per subject
    subject_counts: Dict[str, int] = {}
    for r in subtopic_rows:
        subj = r['subject']
        subject_counts[subj] = subject_counts.get(subj, 0) + 1

    print("\n=== SUBTOPIC INDEX BACKFILL SUMMARY PER SUBJECT ===")
    for subj, cnt in sorted(subject_counts.items()):
        print(f"  - {subj.upper()}: {cnt} subtopics indexed")

if __name__ == '__main__':
    backfill_subtopic_index()
