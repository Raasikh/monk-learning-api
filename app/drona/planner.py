import json
import logging
import time
from typing import Dict, Any, List, Optional
from fastapi import HTTPException
from app.db import supabase
from app.drona.models import get_drona_client, get_model_name, PLANNER_TIMEOUT_S
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

    if not (6 <= len(segments) <= 9):
        raise ValueError(f"Segment count must be between 6 and 9, got {len(segments)}")

    for idx, seg in enumerate(segments, 1):
        if not isinstance(seg, dict):
            raise ValueError(f"Segment {idx} is not an object")
        
        for req_field in ("objective", "teaching_notes", "board_content"):
            val = seg.get(req_field)
            if not val or not str(val).strip():
                raise ValueError(f"Segment {idx} missing required field '{req_field}'")

        # Board content item count validation. Min stays at 6 so plans authored
        # under the old 6-9 target (including every cached plan) still validate;
        # newly authored segments target 9-12 (see planner_segment.md).
        bc = seg.get("board_content", [])
        if not isinstance(bc, list):
            raise ValueError(f"Segment {idx} board_content must be an array, got {type(bc).__name__}")
        if len(bc) < 6:
            raise ValueError(f"Segment {idx} board_content has {len(bc)} items (minimum 6 required)")
        if len(bc) > 12:
            raise ValueError(f"Segment {idx} board_content has {len(bc)} items (maximum 12 allowed)")

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
    """
    Robust JSON LaTeX escape repair:
    Doubles any backslash in JSON string values that is NOT already double-escaped (\\\\) or an escaped quote (\\").
    This fixes \\Delta, \\text, \\frac, \\neq, \\vec, etc. without breaking valid JSON string structure.
    """
    if not text:
        return ""
    import re
    pattern = re.compile(r'(?<!\\)\\(?!["\\])')
    return pattern.sub(r'\\\\', text)

def sanitize_double_escaped_latex(obj: Any, count_acc: Optional[List[int]] = None) -> Any:
    """Recursively cleans double-escaped backslashes (\\\\\\\\) in parsed plan JSON strings."""
    is_top_level = False
    if count_acc is None:
        count_acc = [0]
        is_top_level = True

    res_obj = obj
    if isinstance(obj, dict):
        res_obj = {k: sanitize_double_escaped_latex(v, count_acc) for k, v in obj.items()}
    elif isinstance(obj, list):
        res_obj = [sanitize_double_escaped_latex(v, count_acc) for v in obj]
    elif isinstance(obj, str):
        if "\\\\" in obj:
            count_acc[0] += 1
            res_obj = obj.replace("\\\\", "\\")

    if is_top_level and count_acc[0] > 0:
        logger.warning(f"⚠️ [DOUBLE ESCAPE SANITIZED] Cleaned {count_acc[0]} double-escaped LaTeX fields in lesson plan payload.")

    return res_obj

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
    messages = [
        {"role": "system", "content": planner_prompt},
        {"role": "user", "content": user_prompt}
    ]
    raw_response_content = ""

    while attempts < 2:
        attempts += 1
        res = client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            # A 9-segment plan with 6-9 LaTeX board items per segment runs to
            # ~30k characters. Left implicit, the provider default can cut the
            # response mid-object and the only symptom is a JSON parse error at
            # a large offset, which is indistinguishable from a bad escape.
            max_tokens=16384,
            timeout=PLANNER_TIMEOUT_S,
            extra_body={"thinking": {"type": "disabled"}}
        )

        raw_response_content = res.choices[0].message.content or ""
        cleaned = strip_fences(raw_response_content)

        # Log the shape of every authoring response so the NEXT parse failure
        # diagnoses itself: finish_reason 'length' means truncation (raise
        # max_tokens or split the plan), anything else means malformed content
        # (unescaped quote or backslash in a string value).
        finish_reason = getattr(res.choices[0], "finish_reason", None)
        usage = getattr(res, "usage", None)
        logger.info(
            f"[PLANNER RESPONSE] attempt={attempts} finish_reason={finish_reason} "
            f"output_tokens={getattr(usage, 'completion_tokens', None)} chars={len(raw_response_content)}"
        )
        if finish_reason == "length":
            logger.error(
                f"❌ [PLANNER TRUNCATED] Model hit the output cap at {len(raw_response_content)} chars — "
                f"the JSON is incomplete by construction. Raise max_tokens or author the plan per-segment."
            )

        # Try raw json.loads FIRST (§2 requirement: execute repair ONLY in exception path)
        try:
            plan_json = json.loads(cleaned)
        except json.JSONDecodeError as decode_err:
            logger.warning(f"⚠️ [JSON DECODE FAIL] Direct json.loads failed: {decode_err}. Trying repair_json_escapes fallback...")
            try:
                repaired = repair_json_escapes(cleaned)
                plan_json = json.loads(repaired, strict=False)
            except Exception as repair_err:
                logger.error(f"❌ [REPAIR JSON FAIL] Both raw and repaired JSON parse failed: {repair_err}")
                if attempts < 2:
                    messages.append({"role": "assistant", "content": raw_response_content})
                    messages.append({"role": "user", "content": f"Your previous response had invalid JSON formatting: {repair_err}. Please output strictly valid JSON."})
                    continue
                else:
                    raise HTTPException(status_code=500, detail=f"LLM produced unparseable JSON: {repair_err}")

        try:
            # Post-parsing validation & double-escape sanitization step
            plan_json = sanitize_double_escaped_latex(plan_json)
            validate_plan_json(plan_json)
            
            segment_count = len(plan_json["segments"])
            prompt_ver = get_prompt_version()
            source_model_tag = f"{model_name}-thinking-off"

            # INSERT into lesson_plans table (§3.5) with 409 conflict handling
            try:
                ins_res = supabase.table("lesson_plans").insert([{
                    "chapter_id": chapter_id,
                    "subtopic_key": subtopic_key,
                    "plan_json": plan_json,
                    "grounded": is_grounded,
                    "segment_count": segment_count,
                    "source_model": source_model_tag,
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
            # Detailed Offset Logging
            logger.error(f"[PLANNER PARSE ERROR - Attempt {attempts}] Exception: {e}")
            logger.error(f"[PLANNER RAW RESPONSE FIRST 2000 CHARS]:\n{cleaned[:2000]}")
            
            if isinstance(e, json.JSONDecodeError):
                pos = e.pos
                snippet_before = cleaned[max(0, pos - 50):pos]
                failing_char = cleaned[pos] if pos < len(cleaned) else ""
                snippet_after = cleaned[pos + 1:min(len(cleaned), pos + 50)]
                logger.error(f"[PARSE OFFSET INFO] pos={pos}, line={e.lineno}, col={e.colno}")
                logger.error(f"[CHAR AT OFFSET]: repr={repr(failing_char)}")
                logger.error(f"[SNIPPET AROUND OFFSET]: '{snippet_before}>>> {failing_char} <<<{snippet_after}'")
                
                repaired_before = repaired[max(0, pos - 50):pos]
                repaired_failing = repaired[pos] if pos < len(repaired) else ""
                repaired_after = repaired[pos + 1:min(len(repaired), pos + 50)]
                logger.error(f"[REPAIRED SNIPPET AROUND OFFSET]: '{repaired_before}>>> {repaired_failing} <<<{repaired_after}'")

            # Lightweight Re-emission instead of fresh authoring turn from scratch
            if attempts < 2:
                logger.info("Attempting lightweight JSON re-emission turn (preserving generated content)...")
                messages.append({"role": "assistant", "content": raw_response_content})
                # Two different failure classes need two different instructions.
                # A JSON syntax error means "same content, fix the encoding". A
                # schema error means the CONTENT is wrong and must be
                # restructured — telling the model to "re-emit the exact same
                # plan" there guarantees it fails again the same way.
                if isinstance(e, json.JSONDecodeError):
                    guidance = (
                        f"The generated JSON could not be parsed: {e}. "
                        "Re-emit the exact same plan, fixing ONLY the JSON encoding:\n"
                        "1. ALL backslashes in LaTeX strings must be double backslashes "
                        "(\\\\frac, \\\\vec, \\\\text, \\\\theta).\n"
                        "2. Never use a raw double quote inside a string value — an "
                        "unescaped \" ends the string early. Use single quotes in prose, "
                        "or escape it as \\\".\n"
                        "3. Do not truncate. Close every bracket."
                    )
                else:
                    guidance = (
                        f"The plan is valid JSON but FAILED SCHEMA VALIDATION: {e}\n\n"
                        "Rewrite the plan so it satisfies the schema. This is a CONTENT change, "
                        "not an encoding change — do not simply re-emit the same structure.\n"
                        "Hard requirements:\n"
                        "- EXACTLY 6 to 9 segments. If you produced more, MERGE related segments "
                        "until you are within range; do not drop the material, consolidate it.\n"
                        "- EXACTLY 6 to 9 board_content items per segment.\n"
                        "- 2 to 3 expected_misconceptions per checkpoint.\n"
                        "- wrapup_points must have exactly one entry per segment."
                    )
                messages.append({"role": "user", "content": guidance})

    raise RuntimeError(f"Planner failed validation after 2 attempts: {last_err}")

# ── Streaming (two-pass) authoring ──────────────────────────────────────────
#
# Monolithic authoring measured 103-171s and produced up to 37k characters in
# one response, which is what truncated and broke the JSON. Splitting it:
#   pass 1  outline        — all segment titles/objectives in one view, so the
#                            teaching arc stays coherent
#   pass 2  segment detail — one segment per call, ~3k chars, cannot truncate
# Segment 1 is authored inline so teaching can start; 2..N fill in behind it
# while the student is still in segment 1.
#
# Partial plans are marked in-band. A migration would be cleaner, but these keys
# are ignored by every existing reader and avoid a schema change.
PLAN_STATUS_KEY = "_status"
PLAN_EXPECTED_KEY = "_expected_segments"


def _plan_is_complete(plan_json: Dict[str, Any]) -> bool:
    return (plan_json or {}).get(PLAN_STATUS_KEY, "complete") == "complete"


def _author_outline(chap_data: Dict[str, Any], sub_title: str, subtopic_key: str,
                    structure_block: str, depth_block: str) -> Dict[str, Any]:
    client = get_drona_client()
    res = client.chat.completions.create(
        model=get_model_name("planner"),
        messages=[
            {"role": "system", "content": load_prompt("planner_outline.md")},
            {"role": "user", "content": (
                f"Chapter: {chap_data['name']} ({chap_data.get('subject')})\n"
                f"Subtopic: {sub_title} (Key: {subtopic_key})\n\n"
                f"{structure_block}\n\n{depth_block}\n\n"
                "Produce the outline JSON."
            )},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=4096,
        timeout=PLANNER_TIMEOUT_S,
        extra_body={"thinking": {"type": "disabled"}},
    )
    outline = sanitize_double_escaped_latex(json.loads(strip_fences(res.choices[0].message.content or "{}")))
    segs = outline.get("segments") or []
    if not (6 <= len(segs) <= 9):
        raise ValueError(f"Outline segment count must be 6-9, got {len(segs)}")
    return outline


def _author_segment(chap_data: Dict[str, Any], sub_title: str, outline: Dict[str, Any],
                    index: int, depth_block: str) -> Dict[str, Any]:
    """Authors one full segment. index is 0-based."""
    segs = outline["segments"]
    stub = segs[index]
    others = "\n".join(
        f"  {i+1}. {s.get('title')} — {s.get('objective')}" for i, s in enumerate(segs) if i != index
    )
    client = get_drona_client()
    messages = [
        {"role": "system", "content": load_prompt("planner_segment.md")},
        {"role": "user", "content": (
            f"Chapter: {chap_data['name']} ({chap_data.get('subject')})\n"
            f"Subtopic: {sub_title}\n\n"
            f"YOU ARE AUTHORING SEGMENT {index + 1} OF {len(segs)}:\n"
            f"  title: {stub.get('title')}\n"
            f"  objective: {stub.get('objective')}\n"
            f"  teaching_notes: {stub.get('teaching_notes')}\n\n"
            f"OTHER SEGMENTS (context only — do NOT teach these):\n{others}\n\n"
            f"{depth_block}\n\n"
            "Produce the full JSON object for YOUR segment only."
        )},
    ]
    last_err = None
    for attempt in (1, 2):
        res = client.chat.completions.create(
            model=get_model_name("planner"),
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=4096,
            timeout=PLANNER_TIMEOUT_S,
            extra_body={"thinking": {"type": "disabled"}},
        )
        raw = res.choices[0].message.content or ""
        try:
            seg = sanitize_double_escaped_latex(json.loads(strip_fences(raw)))
        except json.JSONDecodeError:
            seg = sanitize_double_escaped_latex(json.loads(repair_json_escapes(strip_fences(raw)), strict=False))
        seg["id"] = index + 1
        bc = seg.get("board_content")
        cp = seg.get("checkpoint") or {}
        # Prompt asks for 9-12; accept 8 so a near-miss doesn't burn a retry.
        if isinstance(bc, list) and 8 <= len(bc) <= 12 and cp.get("question") and cp.get("model_answer") and cp.get("rubric"):
            return seg
        last_err = f"segment {index+1}: board_content={len(bc) if isinstance(bc, list) else 'n/a'}, checkpoint keys={list(cp)}"
        logger.warning(f"⚠️ [SEGMENT RETRY] {last_err} (attempt {attempt}/2)")
        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": (
                f"That segment failed validation: {last_err}. Re-author it with EXACTLY 9-12 "
                "board_content items and a complete checkpoint (question, model_answer, rubric, "
                "2-3 expected_misconceptions)."
            )},
        ]
    raise ValueError(f"Segment authoring failed after 2 attempts — {last_err}")


def _fill_remaining_segments(plan_id: str, chap_data: Dict[str, Any], sub_title: str,
                             outline: Dict[str, Any], first_segment: Dict[str, Any],
                             depth_block: str) -> None:
    """Authors segments 2..N in parallel and writes the completed plan. Runs in a
    background thread while the student is being taught segment 1."""
    from concurrent.futures import ThreadPoolExecutor
    total = len(outline["segments"])
    try:
        with ThreadPoolExecutor(max_workers=4) as ex:
            rest = list(ex.map(
                lambda i: _author_segment(chap_data, sub_title, outline, i, depth_block),
                range(1, total),
            ))
        plan_json = {
            "topic": outline.get("topic") or sub_title,
            "grounded": outline.get("grounded", True),
            "estimated_minutes": outline.get("estimated_minutes", 30),
            "segments": [first_segment] + rest,
            "wrapup_points": outline.get("wrapup_points") or [],
        }
        wp = plan_json["wrapup_points"]
        if len(wp) != total:
            plan_json["wrapup_points"] = (wp + [s.get("objective", "") for s in plan_json["segments"]])[:total]
        validate_plan_json(plan_json)
        plan_json[PLAN_STATUS_KEY] = "complete"
        plan_json[PLAN_EXPECTED_KEY] = total
        supabase.table("lesson_plans").update({
            "plan_json": plan_json, "segment_count": total,
        }).eq("id", plan_id).execute()
        logger.info(f"✅ [PLAN COMPLETE] plan={plan_id[:8]} all {total} segments authored and validated")
    except Exception as e:
        # The student keeps whatever segments exist; the plan stays 'partial' so
        # the next lookup regenerates rather than serving a half lesson as cached.
        logger.error(f"❌ [BACKGROUND PLAN FILL FAILED] plan={plan_id[:8]}: {e}")


def create_plan_streaming(chapter_id: str, subtopic_key: str) -> Dict[str, Any]:
    """Authors the outline + segment 1, stores them, and returns immediately.
    Segments 2..N are authored in the background."""
    import threading

    chap_res = supabase.table("chapters").select("name, subject").eq("id", chapter_id).execute()
    chap_data = chap_res.data[0] if chap_res.data else {"name": "Chapter", "subject": "Physics"}
    sub_res = supabase.table("subtopic_index").select("subtopic").eq("chapter_id", chapter_id).eq("subtopic_key", subtopic_key).execute()
    sub_title = sub_res.data[0]["subtopic"] if sub_res.data else subtopic_key.replace("-", " ").title()

    structure_block, depth_block, is_grounded = retrieve_dual_blocks(chapter_id, sub_title)

    t0 = time.time()
    outline = _author_outline(chap_data, sub_title, subtopic_key, structure_block, depth_block)
    t_outline = time.time() - t0
    first_segment = _author_segment(chap_data, sub_title, outline, 0, depth_block)
    total = len(outline["segments"])
    logger.info(
        f"⚡ [STREAMING PLAN] '{subtopic_key}' outline={t_outline:.0f}s "
        f"+ segment 1={time.time()-t0-t_outline:.0f}s -> teaching can start ({total} segments planned)"
    )

    partial_json = {
        "topic": outline.get("topic") or sub_title,
        "grounded": outline.get("grounded", is_grounded),
        "estimated_minutes": outline.get("estimated_minutes", 30),
        "segments": [first_segment],
        "wrapup_points": outline.get("wrapup_points") or [],
        PLAN_STATUS_KEY: "partial",
        PLAN_EXPECTED_KEY: total,
    }
    ins = supabase.table("lesson_plans").insert([{
        "chapter_id": chapter_id,
        "subtopic_key": subtopic_key,
        "plan_json": partial_json,
        "grounded": is_grounded,
        "segment_count": total,
        "source_model": f"{get_model_name('planner')}-thinking-off-streaming",
        "prompt_version": get_prompt_version(),
    }]).execute()
    if not ins.data:
        raise RuntimeError("Failed to insert streaming lesson plan")
    row = ins.data[0]

    threading.Thread(
        target=_fill_remaining_segments,
        args=(row["id"], chap_data, sub_title, outline, first_segment, depth_block),
        daemon=True,
    ).start()
    return row


def get_or_create_plan(chapter_id: str, subtopic_key: str) -> Dict[str, Any]:
    """Lazy cache lookup (§3.1): Hit -> return from DB (if valid). Miss/Invalid -> LLM authoring + INSERT."""
    plan_res = (
        supabase.table("lesson_plans")
        .select("*")
        .eq("chapter_id", chapter_id)
        .eq("subtopic_key", subtopic_key)
        .execute()
    )
    if plan_res.data:
        cached_plan = plan_res.data[0]
        plan_json = cached_plan.get("plan_json", {})

        # A plan still being filled in the background is not a cache hit for a
        # NEW student — serving it would teach one segment and stop. Give the
        # background thread a grace window, then treat it as stale.
        if not _plan_is_complete(plan_json):
            age_s = 1e9
            try:
                from datetime import datetime, timezone
                created = datetime.fromisoformat(str(cached_plan.get("created_at", "")).replace("Z", "+00:00"))
                age_s = (datetime.now(timezone.utc) - created).total_seconds()
            except Exception:
                pass
            if age_s < 300:
                logger.info(f"[PLAN PARTIAL] '{subtopic_key}' still filling ({age_s:.0f}s old) — serving it; segments arrive as authored.")
                return cached_plan
            logger.warning(f"⚠️ [PLAN PARTIAL STALE] '{subtopic_key}' never completed ({age_s:.0f}s old). Regenerating.")
            try:
                supabase.table("lesson_plans").delete().eq("id", cached_plan["id"]).execute()
            except Exception as del_err:
                logger.error(f"Failed to delete stale partial plan: {del_err}")
            return create_plan_streaming(chapter_id, subtopic_key)

        try:
            validate_plan_json(plan_json)
            logger.info(f"CACHE HIT (VALIDATED) for plan chapter_id={chapter_id}, subtopic_key={subtopic_key}")
            return cached_plan
        except Exception as val_err:
            logger.warning(
                f"⚠️ [CACHED PLAN INVALID] Plan {cached_plan.get('id')} for subtopic '{subtopic_key}' "
                f"failed schema validation: {val_err}. Regenerating..."
            )
            # Regenerate BEFORE deleting. The old order purged first and then
            # called the planner: when authoring failed (unparseable JSON, API
            # error) the cached plan was already gone, so the student got a 500
            # and the plan was destroyed permanently. Observed on two subtopics.
            try:
                supabase.table("lesson_plans").delete().eq("id", cached_plan["id"]).execute()
                return create_plan_streaming(chapter_id, subtopic_key)
            except Exception as regen_err:
                logger.error(
                    f"❌ [PLAN REGENERATION FAILED] Could not replace invalid plan for '{subtopic_key}': {regen_err}. "
                    f"Restoring the previous cached plan so the session can still run in a degraded state — "
                    f"it will teach fewer board items than the 6-9 floor until authoring succeeds."
                )
                try:
                    # Put the old row back rather than leaving the subtopic with
                    # no plan at all. A thin lesson beats a hard failure.
                    restore = {k: v for k, v in cached_plan.items() if k != "id"}
                    restored = supabase.table("lesson_plans").insert([restore]).execute()
                    if restored.data:
                        return restored.data[0]
                except Exception as restore_err:
                    logger.error(f"❌ [PLAN RESTORE FAILED] {restore_err}")
                raise

    logger.info(f"CACHE MISS for chapter_id={chapter_id}, subtopic_key={subtopic_key} — streaming author (outline + segment 1)...")
    try:
        return create_plan_streaming(chapter_id, subtopic_key)
    except Exception as stream_err:
        logger.error(f"❌ [STREAMING AUTHOR FAILED] {stream_err}. Falling back to single-pass authoring.")
        return create_plan_with_llm(chapter_id, subtopic_key)
