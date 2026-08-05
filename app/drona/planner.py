import json
import logging
from typing import Dict, Any, List, Optional
from app.db import supabase
from app.drona.models import get_drona_client, get_model_name
from app.drona.prompt_loader import load_prompt, get_prompt_version
from app.drona.retrieval import retrieve_dual_blocks

logger = logging.getLogger("drona.planner")

def validate_plan_json(data: Dict[str, Any]) -> None:
    """Strict §3.4 validation for authored lesson plan JSON."""
    if not isinstance(data, dict):
        raise ValueError("Plan payload is not a JSON object")

    segments = data.get("segments")
    if not isinstance(segments, list):
        raise ValueError("Plan missing 'segments' array")

    if not (2 <= len(segments) <= 6):
        raise ValueError(f"Segment count must be between 2 and 6, got {len(segments)}")

    for idx, seg in enumerate(segments, 1):
        if not isinstance(seg, dict):
            raise ValueError(f"Segment {idx} is not an object")
        
        for req_field in ("objective", "teaching_notes", "board_content"):
            val = seg.get(req_field)
            if not val or not str(val).strip():
                raise ValueError(f"Segment {idx} missing required field '{req_field}'")

        # Balanced $ and $$ check in board_content
        board_text = str(seg.get("board_content", ""))
        double_dollars = board_text.count("$$")
        single_dollars = board_text.count("$") - (double_dollars * 2)
        if double_dollars % 2 != 0:
            raise ValueError(f"Segment {idx} board_content has unbalanced '$$' delimiters")
        if single_dollars % 2 != 0:
            raise ValueError(f"Segment {idx} board_content has unbalanced '$' delimiters")

        # Checkpoint validation
        cp = seg.get("checkpoint")
        if not isinstance(cp, dict):
            raise ValueError(f"Segment {idx} missing 'checkpoint' object")
        
        for cp_field in ("question", "model_answer", "rubric"):
            if not cp.get(cp_field) or not str(cp.get(cp_field)).strip():
                raise ValueError(f"Segment {idx} checkpoint missing field '{cp_field}'")
        
        misconceptions = cp.get("expected_misconceptions")
        if not isinstance(misconceptions, list) or not (2 <= len(misconceptions) <= 3):
            raise ValueError(f"Segment {idx} checkpoint must have 2-3 expected_misconceptions")

    wrapup = data.get("wrapup_points")
    if not isinstance(wrapup, list) or len(wrapup) != len(segments):
        raise ValueError(f"wrapup_points length ({len(wrapup) if isinstance(wrapup, list) else 0}) must match segment count ({len(segments)})")

def strip_fences(text: str) -> str:
    """Strips Markdown ```json ... ``` code fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text

def repair_json_escapes(text: str) -> str:
    """Repairs unescaped LaTeX backslashes inside JSON string literals before json.loads."""
    import re
    # Match single backslashes that are NOT valid JSON escape sequences (\", \\, \/, \b, \f, \n, \r, \t, \uXXXX)
    pattern = re.compile(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})')
    return pattern.sub(r'\\\\', text)

def create_plan_with_llm(chapter_id: str, subtopic_key: str) -> Dict[str, Any]:
    """Authored lesson plan generation using deepseek-v4-pro with dual retrieval blocks."""
    # Lookup chapter name & subtopic title
    chap_res = supabase.table("chapters").select("name, subject").eq("id", chapter_id).execute()
    chap_data = chap_res.data[0] if chap_res.data else {"name": "Chapter", "subject": "Physics"}

    sub_res = supabase.table("subtopic_index").select("subtopic").eq("chapter_id", chapter_id).eq("subtopic_key", subtopic_key).execute()
    sub_title = sub_res.data[0]["subtopic"] if sub_res.data else subtopic_key.replace("-", " ").title()

    # Retrieve dual blocks (§3.2)
    structure_block, depth_block, is_grounded = retrieve_dual_blocks(chapter_id, sub_title)

    planner_prompt = load_prompt("planner.md")
    model_name = get_model_name("planner")

    user_prompt = f"""
Chapter: {chap_data['name']} ({chap_data['subject']})
Subtopic: {sub_title} (Key: {subtopic_key})

{structure_block}

{depth_block}

Author a complete lesson plan JSON following the instructions in the system prompt.
"""

    client = get_drona_client()
    attempts = 0
    last_err = None

    while attempts < 2:
        attempts += 1
        messages = [
            {"role": "system", "content": planner_prompt},
            {"role": "user", "content": user_prompt}
        ]
        if attempts > 1 and last_err:
            messages.append({"role": "user", "content": f"Previous JSON failed validation: {last_err}. Please output strictly valid JSON matching the schema."})

        res = client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0
        )

        content = res.choices[0].message.content or ""
        cleaned = strip_fences(content)
        repaired = repair_json_escapes(cleaned)

        try:
            plan_json = json.loads(repaired)
            validate_plan_json(plan_json)
            
            segment_count = len(plan_json["segments"])
            prompt_ver = get_prompt_version()

            # INSERT into lesson_plans table (§3.5) with 409 conflict handling
            try:
                ins_res = supabase.table("lesson_plans").insert([{
                    "chapter_id": chapter_id,
                    "subtopic_key": subtopic_key,
                    "plan_json": plan_json,
                    "grounded": is_grounded,
                    "segment_count": segment_count,
                    "source_model": model_name,
                    "prompt_version": prompt_ver
                }]).execute()
                if ins_res.data:
                    return ins_res.data[0]
            except Exception as db_err:
                err_msg = str(db_err)
                if "unique" in err_msg.lower() or "duplicate" in err_msg.lower() or "23505" in err_msg or "409" in err_msg or "lesson_plans_subtopic_idx" in err_msg:
                    logger.info(f"Unique constraint conflict for subtopic '{subtopic_key}'. Returning existing plan from DB.")
                    existing = supabase.table("lesson_plans").select("*").eq("chapter_id", chapter_id).eq("subtopic_key", subtopic_key).execute()
                    if existing.data:
                        return existing.data[0]
                raise db_err

            raise RuntimeError("Failed to insert lesson plan into DB")
        except Exception as e:
            last_err = str(e)
            logger.warning(f"Planner validation attempt {attempts} failed: {e}")

    raise RuntimeError(f"Planner failed validation after 2 attempts: {last_err}")

def get_or_create_plan(chapter_id: str, subtopic_key: str) -> Dict[str, Any]:
    """Lazy cache lookup (§3.1): Hit -> return from DB. Miss -> LLM authoring + INSERT."""
    # 1. SELECT * FROM lesson_plans WHERE chapter_id = %s AND subtopic_key = %s
    plan_res = (
        supabase.table("lesson_plans")
        .select("*")
        .eq("chapter_id", chapter_id)
        .eq("subtopic_key", subtopic_key)
        .execute()
    )
    if plan_res.data:
        logger.info(f"CACHE HIT for plan chapter_id={chapter_id}, subtopic_key={subtopic_key}")
        return plan_res.data[0]

    logger.info(f"CACHE MISS for plan chapter_id={chapter_id}, subtopic_key={subtopic_key} — calling planner LLM...")
    return create_plan_with_llm(chapter_id, subtopic_key)
