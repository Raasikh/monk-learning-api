"""Decides where a student's requested topic belongs, BEFORE a session starts.

Three outcomes:
  ok             -> the topic is a subtopic of the chapter they are in; teach it
  other_chapter  -> it is in the syllabus, but a different chapter owns it
  out_of_syllabus-> not Class 11-12 JEE/NEET/CBSE material

Deliberately does NOT do a vector scan. The previous routing path
(evaluate_free_text_gate) pulled every row of pdf_chunks with its 1536-dim
embedding into memory on each call — 5,266 rows and growing — to answer a
question the catalogue already answers. Chapter names plus subtopic_index are
small, authoritative, and cheap to match against.

Uses gpt-4o-mini, matching the existing classify_with_llm precedent, so routing
never contends with DeepSeek for a live turn.
"""
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

from app.db import supabase

logger = logging.getLogger("drona.topic_router")

ROUTER_MODEL = "gpt-4o-mini"
ROUTER_TIMEOUT_S = 20.0

_openai: Optional[OpenAI] = None


def _client() -> OpenAI:
    global _openai
    if _openai is None:
        _openai = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=ROUTER_TIMEOUT_S, max_retries=1)
    return _openai


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).strip()


def _local_match(utterance: str, subtopics: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Exact then substring match against the chapter's own subtopics — free, and
    catches the common case where the student tapped one of our own chips."""
    u = _norm(utterance)
    if not u:
        return None
    for s in subtopics:
        if u == _norm(s.get("subtopic")) or u == _norm(s.get("subtopic_key")):
            return s
    if len(u) > 3:
        for s in subtopics:
            name = _norm(s.get("subtopic"))
            if name and (u in name or name in u):
                return s
    return None


def _resolve_chapter(name: Optional[str], by_name: Dict[str, Any],
                     chapters: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Maps the model's chapter_name onto a real row.

    Exact match is not enough: candidates are listed as
    "Gravitation (Physics, Class 11)" and the model frequently copies the whole
    line, so a bare lookup silently fell through to 'ambiguous' even when the
    routing decision was correct.
    """
    raw = (name or "").strip()
    if not raw:
        return None
    for candidate in (raw, re.sub(r"\s*\(.*$", "", raw)):
        hit = by_name.get(candidate.strip().lower())
        if hit:
            return hit
    needle = _norm(re.sub(r"\s*\(.*$", "", raw))
    if len(needle) < 4:
        return None
    for c in chapters:
        cname = _norm(c["name"])
        if cname and (cname == needle or needle in cname or cname in needle):
            return c
    return None


ROUTER_SYSTEM = """You route a student's request to the right chapter of the Indian
Class 11-12 syllabus (JEE / NEET / CBSE).

Return ONLY JSON: {"verdict": "...", "chapter_name": "...", "reason": "..."}

verdict must be one of:
  "current_chapter"  - the request is covered by the chapter the student is already in
  "other_chapter"    - it is Class 11-12 Physics/Chemistry/Maths/Biology, but a
                       DIFFERENT chapter in the provided list covers it
  "out_of_syllabus"  - not Class 11-12 STEM syllabus material (general chat, exam
                       strategy, other subjects, trivia)

chapter_name must be the chapter's NAME ONLY, copied from the candidate list with the
bracketed subject/class suffix REMOVED — e.g. for "- Gravitation (Physics, Class 11)"
return "Gravitation". Set it when verdict is "other_chapter"; otherwise null.
reason: 10 words max.

Be strict: only say "current_chapter" if the current chapter genuinely covers it."""


def route_topic(utterance: str, current_chapter_id: Optional[str] = None) -> Dict[str, Any]:
    utterance = (utterance or "").strip()
    if not utterance:
        return {"status": "ambiguous", "options": [], "message": "Tell me what you'd like to learn."}

    chapters = supabase.table("chapters").select("id,name,subject,class_level").execute().data or []
    by_name = {(c["name"] or "").strip().lower(): c for c in chapters}
    current = next((c for c in chapters if c["id"] == current_chapter_id), None)

    # 1. Free local resolution inside the current chapter.
    if current_chapter_id:
        subs = supabase.table("subtopic_index").select("id,subtopic,subtopic_key") \
            .eq("chapter_id", current_chapter_id).execute().data or []
        hit = _local_match(utterance, subs)
        if hit:
            logger.info(f"[TOPIC ROUTER] local match '{utterance[:40]}' -> {hit['subtopic_key']}")
            return {"status": "ok", "chapter_id": current_chapter_id,
                    "subtopic": hit["subtopic"], "subtopic_key": hit["subtopic_key"]}

    # 2. Ask the router which chapter owns it.
    candidates = "\n".join(
        f"- {c['name']} ({(c.get('subject') or '').title()}, Class {c.get('class_level')})"
        for c in chapters
    )
    ctx = (
        f"Student request: \"{utterance}\"\n\n"
        f"Current chapter: {current['name'] if current else '(none - free text entry)'}\n\n"
        f"Candidate chapters:\n{candidates}"
    )
    try:
        res = _client().chat.completions.create(
            model=ROUTER_MODEL,
            messages=[{"role": "system", "content": ROUTER_SYSTEM}, {"role": "user", "content": ctx}],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        parsed = json.loads(res.choices[0].message.content or "{}")
    except Exception as e:
        # Never block a student on a router failure — fall through to the
        # chapter's own subtopic list and let them pick.
        logger.error(f"❌ [TOPIC ROUTER FAILED] {e}. Falling back to subtopic choice.")
        parsed = {"verdict": "current_chapter"}

    verdict = (parsed.get("verdict") or "").strip()
    logger.info(f"[TOPIC ROUTER] '{utterance[:40]}' -> {verdict} ({parsed.get('reason')})")

    if verdict == "out_of_syllabus":
        return {"status": "out_of_syllabus",
                "message": "That one's outside the Class 11-12 JEE/NEET syllabus, so I can't teach it here."}

    if verdict == "other_chapter":
        target = _resolve_chapter(parsed.get("chapter_name"), by_name, chapters)
        if target and target["id"] != current_chapter_id:
            return {
                "status": "other_chapter",
                "chapter": {"id": target["id"], "name": target["name"],
                            "subject": target.get("subject"), "class_level": target.get("class_level")},
                "message": f"That's covered in {target['name']}, not this chapter.",
            }

    # current_chapter, or other_chapter we could not resolve to a real row:
    # hand back this chapter's subtopics so the student can choose.
    subs = []
    if current_chapter_id:
        subs = supabase.table("subtopic_index").select("subtopic") \
            .eq("chapter_id", current_chapter_id).execute().data or []
    return {
        "status": "ambiguous",
        "chapter_id": current_chapter_id,
        "options": [s["subtopic"] for s in subs],
        "message": "Which of these would you like to cover?",
    }
