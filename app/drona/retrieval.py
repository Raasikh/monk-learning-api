import os
import math
import json
import logging
from typing import Dict, List, Optional, Tuple
from openai import OpenAI
from app.db import supabase

logger = logging.getLogger("drona.retrieval")

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Two-stage gate shortcut threshold:
COSINE_SHORTCUT_THRESHOLD = 0.50

def get_embedding(text: str) -> List[float]:
    """Generates 1536-dimensional embedding using text-embedding-3-small."""
    res = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return res.data[0].embedding

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Computes cosine similarity between two vector embeddings."""
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)

def retrieve_lesson_structure(chapter_id: str, subtopic: str) -> List[dict]:
    """Ordered lesson_sections authored for THIS subtopic, or nothing.

    Returns [] when the subtopic has no authored sections. It used to return
    `all_sections[:10]` — the chapter's OPENING ten sections — and
    retrieve_dual_blocks then presented them to the planner under the header
    "already validated and voiced, follow this teaching order". The planner
    did what it was told, so every unmatched concept was planned as its
    chapter's introduction: "Electric Field Lines" came back as a lesson on
    charge, conductors and the gold-leaf electroscope, because that is the
    lesson it was handed.

    Measured 2026-09-03 before this change: 1,023 of 1,154 active concepts
    (88.6%) took that fallback. Only 11.3% were matched to their own
    sections. Every one of the 88.6% produced a plan grounded in the wrong
    lesson and labelled validated.

    An unmatched concept is a content gap to count, not to paper over. The
    planner still receives the concept name, the chapter, and the reference
    depth chunks; it can plan from those. What it must not receive is
    another concept's lesson presented as this one's.
    """
    res = (
        supabase.table('lesson_sections')
        .select('title, board_content, segments_english, position, subtopic')
        .eq('chapter_id', chapter_id)
        .order('position')
        .execute()
    )
    all_sections = res.data or []

    # Filter by matching subtopic (case-insensitive)
    matched = [s for s in all_sections if (s.get('subtopic') or '').lower().strip() == subtopic.lower().strip()]
    if not matched and all_sections:
        sub_norm = subtopic.lower().strip()
        matched = [s for s in all_sections if sub_norm in (s.get('subtopic') or '').lower()]

    if not matched:
        logger.warning(
            f"📭 [NO LESSON SECTIONS] subtopic={subtopic!r} chapter={chapter_id} — "
            f"{len(all_sections)} section(s) exist for this chapter but none match it. "
            f"Planning without a structure block."
        )
    return matched

def retrieve_pdf_chunks(chapter_id: str, query_text: str, top_k: int = 12) -> List[dict]:
    """Queries pdf_chunks for top_k similar chunks by cosine similarity to query_text."""
    query_emb = get_embedding(query_text)
    
    # Attempt Postgres pgvector RPC match first to return top_k directly without fetching all embeddings
    try:
        rpc_res = supabase.rpc("match_pdf_chunks", {
            "query_embedding": query_emb,
            "filter_chapter_id": chapter_id,
            "match_count": top_k
        }).execute()
        if rpc_res.data:
            import logging
            logging.getLogger("uvicorn").info(f"[VECTOR RPC MATCH] match_pdf_chunks returned {len(rpc_res.data)} chunks for chapter {chapter_id}")
            return rpc_res.data
    except Exception as rpc_err:
        import logging
        logging.getLogger("uvicorn").info(f"[VECTOR RPC FALLBACK] match_pdf_chunks RPC not present ({rpc_err}), using in-memory cosine fallback.")

    # Fallback: In-memory vector similarity ranking over chapter chunks
    res = supabase.table('pdf_chunks').select('id, chapter_id, content, embedding, source_file, chunk_index').eq('chapter_id', chapter_id).execute()
    chunks = res.data or []
    if not chunks:
        return []

    scored = []
    for c in chunks:
        emb = c.get('embedding')
        if emb:
            if isinstance(emb, str):
                emb = json.loads(emb)
            score = cosine_similarity(query_emb, emb)
            scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:top_k]]

def retrieve_dual_blocks(chapter_id: str, subtopic: str) -> Tuple[str, str, bool, bool]:
    """Formats the planner's context: [REFERENCE DEPTH] always, and
    [RELATED AUTHORED LESSON] only when one genuinely exists for this
    subtopic."""
    lesson_sections = retrieve_lesson_structure(chapter_id, subtopic)
    
    # Two claims live in this header, and both have to be true.
    #
    # Provenance: it is only written when the sections are genuinely this
    # subtopic's, never as a heading over someone else's lesson.
    #
    # Authority: it used to end "follow this teaching order", which is an
    # instruction, not context. These sections come from the recorded Lessons
    # product (lesson_sections — see lib/lessons.ts in the app, which is their
    # actual owner), authored at that product's own granularity of roughly
    # seven subtopics per chapter. They are supplied here to give the planner
    # MORE context about how this material has been taught before, which is
    # what the design intended — not to hand it a running order to reproduce.
    # Telling the planner to follow them makes a reference into a script, and
    # constrains it to a lesson written for a coarser unit than the concept it
    # is planning.
    structure_lines = []
    if lesson_sections:
        structure_lines.append(
            "[RELATED AUTHORED LESSON — how this material has been taught before, "
            "for reference on coverage, depth and tone]\n"
            "Use it to inform your plan. Do NOT simply follow its order or scope: "
            "it was authored for a broader topic than the concept above, so it may "
            "cover more, less, or adjacent ground. Plan for the concept."
        )
        for idx, s in enumerate(lesson_sections, 1):
            title = s.get('title', f'Section {idx}')
            board = s.get('board_content', '')
            narration = s.get('segments_english', '')
            if isinstance(narration, list):
                narration = " ".join(str(item) for item in narration)
            structure_lines.append(f"Section {idx}: {title}")
            if board:
                structure_lines.append(f"  Board: {str(board)[:200]}")
            if narration:
                structure_lines.append(f"  Narration: {str(narration)[:200]}")

    structure_block = "\n".join(structure_lines)

    # Reference Depth from PDF Chunks
    query_string = f"{subtopic} " + " ".join(s.get('title', '') for s in lesson_sections)
    pdf_chunks = retrieve_pdf_chunks(chapter_id, query_string, top_k=12)

    depth_lines = ["[REFERENCE DEPTH — master PDF, use for accuracy and detail]"]
    if pdf_chunks:
        for idx, chunk in enumerate(pdf_chunks, 1):
            src = chunk.get('source_file', 'master.pdf')
            content = chunk.get('content', '').strip()
            depth_lines.append(f"Chunk {idx} ({src}):\n{content}\n")
    else:
        depth_lines.append("  (No pdf_chunks available for this chapter)")

    depth_block = "\n".join(depth_lines)
    # Two separate facts, because they answer different questions and
    # collapsing them is what hid this bug for three weeks.
    #
    # `grounded` asks: did the planner have real source material for this
    # concept? That is the master-PDF chunks — the primary source, present
    # for 105 of 107 chapters. It was previously `pdf_chunks or
    # lesson_sections`, and lesson_sections was never empty because of the
    # fallback, so the OR made it unconditionally True on every plan ever
    # written. An always-true flag records nothing.
    #
    # `has_recorded_lesson` asks the narrower question: did a lesson authored
    # for THIS subtopic exist to hand over as extra context? That is a
    # minority case by design — lesson_sections belongs to the recorded
    # Lessons product and is authored at its granularity, not per concept —
    # so False here is normal and is not a defect.
    grounded = len(pdf_chunks) > 0
    has_recorded_lesson = len(lesson_sections) > 0

    return structure_block, depth_block, grounded, has_recorded_lesson

def classify_with_llm(student_query: str, candidate_chapters: List[dict]) -> Tuple[bool, Optional[str]]:
    """Stage 2 lightweight LLM classifier (thinking OFF) for top1_score < 0.50 queries."""
    cand_str = "\n".join(f"- {c['name']} ({c['subject'].upper()} Class {c['class_level']})" for c in candidate_chapters)
    
    prompt = f"""You are Drona's syllabus classification engine for Class 11-12 Physics, Chemistry, Mathematics, and Biology (JEE/NEET).
Determine if the student's query (in English, Hinglish, or informal phrasing) is asking to learn or understand a Class 11-12 STEM topic.

Student query: "{student_query}"

Candidate Chapters in Drona's Content Bank:
{cand_str}

Instruction:
Return a JSON object with:
- "in_syllabus": true if the student is asking to learn/understand a Class 11-12 STEM topic (even if informal/Hinglish/vague). Return false if out-of-syllabus (general advice, coaching comparison, exam stress, general trivia, non-STEM).
- "chapter_name": exact name of the matching chapter from the candidates above if in_syllabus is true, otherwise null.

Respond ONLY with valid JSON."""

    try:
        res = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a JSON-only response assistant."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        data = json.loads(res.choices[0].message.content)
        in_syll = data.get("in_syllabus", False)
        ch_name = data.get("chapter_name")
        return in_syll, ch_name
    except Exception as e:
        print(f"LLM classifier error for '{student_query}': {e}")
        return False, None

def evaluate_free_text_gate(student_topic: str) -> Tuple[bool, Optional[str], List[dict], float, str]:
    """Two-Stage Free-Text Gate: Stage 1 Cosine Shortcut (>=0.50) -> Stage 2 LLM Classifier Fallback (<0.50)."""
    topic_emb = get_embedding(student_topic)

    # Fetch pdf_chunks to find max cosine similarity
    res = supabase.table('pdf_chunks').select('chapter_id, content, embedding').execute()
    all_chunks = res.data or []

    if not all_chunks:
        return False, None, [], 0.0, "no_chunks"

    # Score pdf_chunks
    chapter_scores: Dict[str, float] = {}
    for c in all_chunks:
        cid = c['chapter_id']
        emb = c.get('embedding')
        if emb:
            if isinstance(emb, str):
                emb = json.loads(emb)
            sim = cosine_similarity(topic_emb, emb)
            if sim > chapter_scores.get(cid, 0.0):
                chapter_scores[cid] = sim

    if not chapter_scores:
        return False, None, [], 0.0, "empty_scores"

    sorted_ch = sorted(chapter_scores.items(), key=lambda x: x[1], reverse=True)
    top_cid, top_score = sorted_ch[0]

    ch_ids = [item[0] for item in sorted_ch[:5]]
    ch_res = supabase.table('chapters').select('id, name, subject, class_level').in_('id', ch_ids).execute()
    ch_map = {c['id']: c for c in (ch_res.data or [])}
    candidate_chapters = [ch_map[cid] for cid in ch_ids if cid in ch_map]

    # STAGE 1: Cosine Shortcut (>= 0.50) -> Accept immediately, 0 LLM call
    if top_score >= COSINE_SHORTCUT_THRESHOLD:
        return True, top_cid, candidate_chapters[:3], round(top_score, 4), "stage1_cosine_shortcut"

    # STAGE 2: LLM Classifier Fallback (top1 < 0.50) -> Lightweight call for Hinglish/vague/out-of-syllabus
    in_syllabus, matched_name = classify_with_llm(student_topic, candidate_chapters)
    
    if in_syllabus:
        matched_id = top_cid
        if matched_name:
            for c in candidate_chapters:
                if c['name'].lower().strip() == matched_name.lower().strip():
                    matched_id = c['id']
                    break
        return True, matched_id, candidate_chapters[:3], round(top_score, 4), "stage2_llm_accepted"
    else:
        return False, None, candidate_chapters[:3], round(top_score, 4), "stage2_llm_declined"
