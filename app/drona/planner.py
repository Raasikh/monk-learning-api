import json
import logging
import time
from typing import Dict, Any, List, Optional
from fastapi import HTTPException
from app.db import supabase
from app.drona.models import get_drona_client, get_model_name, PLANNER_TIMEOUT_S, thinking_off
from app.drona.prompt_loader import load_prompt, get_prompt_version
from app.drona.json_utils import repair_latex_control_escapes
from app.drona.retrieval import retrieve_dual_blocks
from app.drona.usage import record_call
from app.drona.widget_registry import (
    ROUTE_ARCHETYPE_HIGH,
    WIDGET_VERSIONS,
    render_single_widget_block,
)
from app.drona.concept_archetypes import (
    ARCHETYPE_VERSION,
    concept_archetype_for_session,
)

# Hard ceiling on segments authored for one plan. validate_plan_json accepts
# 6-9, so anything above this is a malformed outline rather than a long lesson,
# and authoring against it bills one call per phantom segment in a detached
# thread. Set above the validator's max so a legitimate plan is never refused.
MAX_SEGMENTS_PER_PLAN = 12

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
        # Undo the OTHER escaping failure, which this function could never see:
        # `\neq` written into JSON is valid JSON, so json.loads had already
        # turned it into a newline plus "eq" before anything got here. A saved
        # Integrals note rendered exactly that — a broken line with a stray
        # "eq" on it. Runs on every string because \theta, \times, \frac,
        # \beta, \alpha and \vec decay the same way.
        res_obj = repair_latex_control_escapes(res_obj)

    if is_top_level and count_acc[0] > 0:
        logger.warning(f"⚠️ [DOUBLE ESCAPE SANITIZED] Cleaned {count_acc[0]} double-escaped LaTeX fields in lesson plan payload.")

    return res_obj

def resolve_topic_title(chapter_id: str, subtopic_key: str) -> str:
    """The human title to author a lesson about, for a concept or subtopic key.

    concepts is checked FIRST because it is now the teaching unit. Looking only
    in subtopic_index missed every concept key and fell through to
    key.replace("-", " ").title(), so the planner was authoring
    "Gauss S Law And Its Applications" — apostrophe eaten, capitalisation
    wrong — and that mangled string went into the prompt as the lesson topic.

    subtopic_index stays as the fallback for plans still keyed the old way, and
    the title-cased key remains the last resort so a missing row cannot stop a
    lesson being authored.
    """
    try:
        rows = supabase.table("concepts").select("name").eq("chapter_id", chapter_id).eq("key", subtopic_key).limit(1).execute().data or []
        if rows and rows[0].get("name"):
            return rows[0]["name"]
    except Exception as err:
        logger.warning(f"concepts title lookup failed for {subtopic_key!r}: {err}")
    try:
        rows = supabase.table("subtopic_index").select("subtopic").eq("chapter_id", chapter_id).eq("subtopic_key", subtopic_key).limit(1).execute().data or []
        if rows and rows[0].get("subtopic"):
            return rows[0]["subtopic"]
    except Exception as err:
        logger.warning(f"subtopic_index title lookup failed for {subtopic_key!r}: {err}")
    logger.warning(f"⚠️ [TITLE FALLBACK] no row for {subtopic_key!r}; authoring against a title-cased key.")
    return subtopic_key.replace("-", " ").title()


# ---------------------------------------------------------------------------
# Plan provenance (migration 0033)
#
# Written on EVERY plan insert. Without this the columns exist and every new
# row silently carries the 'unknown-pre-0033' backfill -- which is exactly the
# prompt_version failure repeated: a field that looks populated and asserts
# nothing. docs/plan-invalidation.md specifies the cache key these feed.
# ---------------------------------------------------------------------------
_PLANNER_PROMPT_FILES = ("planner.md", "planner_outline.md", "planner_segment.md")


def _planner_prompt_hash() -> str:
    """sha256 over THE THREE PLANNER PROMPTS ONLY, sorted by filename.

    Deliberately not get_prompt_version(), which hashes all of prompts/*.md:
    that moves when an unrelated prompt moves and stays still when planner.py
    moves, so it cannot answer "was this plan built by the current planner".
    """
    import hashlib as _h
    from pathlib import Path as _P
    root = _P(__file__).resolve().parent.parent.parent / "prompts"
    h = _h.sha256()
    for name in sorted(_PLANNER_PROMPT_FILES):
        f = root / name
        if f.exists():
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def _planner_code_sha() -> str:
    import hashlib as _h
    from pathlib import Path as _P
    return _h.sha256(_P(__file__).resolve().read_bytes()).hexdigest()[:16]


def _chunk_corpus_version() -> str:
    """Hash of (source_file, chunk_count) pairs -- which corpus grounded this.

    The corpus has been fully replaced twice in two days and nothing in a plan
    row would have said so. Cached per process: it is one query and it cannot
    change mid-run.
    """
    global _CORPUS_VERSION_CACHE
    if _CORPUS_VERSION_CACHE is not None:
        return _CORPUS_VERSION_CACHE
    import hashlib as _h, collections as _c
    try:
        rows, start = [], 0
        while True:
            r = supabase.table("pdf_chunks").select("source_file").range(start, start + 999).execute()
            if not r.data:
                break
            rows += r.data
            start += 1000
        counts = _c.Counter(x["source_file"] for x in rows)
        payload = "".join(f"{k}:{counts[k]};" for k in sorted(counts))
        _CORPUS_VERSION_CACHE = _h.sha256(payload.encode()).hexdigest()[:16]
    except Exception as e:  # provenance must never block a plan
        logger.warning("[PROVENANCE] could not compute chunk_corpus_version: %s", e)
        _CORPUS_VERSION_CACHE = "unavailable"
    return _CORPUS_VERSION_CACHE


_CORPUS_VERSION_CACHE = None


def plan_provenance(model_key: str = "planner") -> dict:
    """The provenance columns for a lesson_plans insert."""
    return {
        "planner_prompt_hash": _planner_prompt_hash(),
        "planner_code_sha": _planner_code_sha(),
        "model_id": get_model_name(model_key),
        "temperature": 0.0,
        "retrieval_config": {
            "top_k": 12,
            "embedding_model": "text-embedding-3-small",
            "rpc": "match_pdf_chunks",
            "structure_match": "exact_only",
        },
        "chunk_corpus_version": _chunk_corpus_version(),
        # No value yet: the classification was read from a corpus that has
        # since been replaced. Stamped so these rows all invalidate the moment
        # it is re-run, which is the correct outcome.
        "archetype_version": "unversioned-2026-09-04",
    }


def _thinking_off() -> dict:
    """Delegates to models.thinking_off(). Kept as a name because three call
    sites use it; the definition lives in models.py so it cannot drift again."""
    return thinking_off()


def create_plan_with_llm(chapter_id: str, subtopic_key: str) -> Dict[str, Any]:
    """Authored lesson plan generation using deepseek-v4-pro with dual retrieval blocks."""
    # Lookup chapter name & subtopic title
    # id is selected because record_call attributes planner spend by chapter.
    # It was omitted here, so every "outline" row ever written carried a null
    # chapter_id — the accounting looked wired up and recorded nothing usable.
    chap_res = supabase.table("chapters").select("id, name, subject").eq("id", chapter_id).execute()
    chap_data = chap_res.data[0] if chap_res.data else {"id": chapter_id, "name": "Chapter", "subject": "Physics"}

    sub_title = resolve_topic_title(chapter_id, subtopic_key)

    # Retrieve dual blocks (§3.2)
    structure_block, depth_block, is_grounded, has_recorded_lesson = retrieve_dual_blocks(chapter_id, sub_title)

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
            extra_body=_thinking_off()
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
                    "prompt_version": prompt_ver,
                    **plan_provenance(),
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
PLAN_ERROR_KEY = "_error"


def _mark_plan_failed(plan_id: str, reason: str) -> None:
    """Record that the background fill DIED, as distinct from still running.

    Both states leave a plan without _status == "complete", so a poller cannot
    tell them apart and has to wait out its whole deadline before calling a
    failure -- minutes, for a thread that is already gone. That is the
    "check that passes on absent information" shape in reverse: an absence
    that reads as patience rather than as death.

    Writes are best-effort. A plan that stays 'partial' because even this
    update failed is the OLD behaviour, which is safe: the next lookup
    regenerates. It is never worse for trying.
    """
    try:
        res = supabase.table("lesson_plans").select("plan_json").eq("id", plan_id).execute()
        pj = (res.data[0].get("plan_json") if res.data else None) or {}
        pj[PLAN_STATUS_KEY] = "failed"
        pj[PLAN_ERROR_KEY] = reason[:500]
        supabase.table("lesson_plans").update({"plan_json": pj}).eq("id", plan_id).execute()
    except Exception as exc:
        logger.error(f"[PLAN MARK-FAILED FAILED] plan={plan_id[:8]}: {exc}")


def _plan_is_complete(plan_json: Dict[str, Any]) -> bool:
    return (plan_json or {}).get(PLAN_STATUS_KEY, "complete") == "complete"


def _author_outline(chap_data: Dict[str, Any], sub_title: str, subtopic_key: str,
                    structure_block: str, depth_block: str) -> Dict[str, Any]:
    client = get_drona_client()
    model_name = get_model_name("planner")
    t0 = time.time()
    try:
        res = client.chat.completions.create(
            model=model_name,
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
            extra_body=_thinking_off(),
        )
    except Exception as exc:
        record_call(model_name, "outline", ok=False,
                    latency_ms=int((time.time() - t0) * 1000),
                    chapter_id=chap_data.get("id"), subtopic_key=subtopic_key, error=str(exc))
        raise
    record_call(model_name, "outline", ok=True, res=res,
                latency_ms=int((time.time() - t0) * 1000),
                chapter_id=chap_data.get("id"), subtopic_key=subtopic_key)
    outline = sanitize_double_escaped_latex(json.loads(strip_fences(res.choices[0].message.content or "{}")))
    segs = outline.get("segments") or []
    if not (6 <= len(segs) <= 9):
        raise ValueError(f"Outline segment count must be 6-9, got {len(segs)}")
    return outline



def _attach_example_diagram(segment: Dict[str, Any], subject: str, sub_title: str,
                           force: bool = False) -> None:
    """Draw the small figure for this segment's worked example, in place.

    `force` skips the worked-example cue and draws anyway. Its ONE caller is
    the precompute decline path below: a segment whose named widget was
    declined has no picture at all, and here — unlike live — nobody is
    waiting, so it is worth the call. Everywhere else the cue still decides.

    A student who can already picture "a 2kg block pushed with 10N" does not
    need this. One who cannot is exactly the student the example was written
    for, and words alone leave them behind — which is the whole reason this
    exists. Roughly 41% of segments work an example, so a lesson gets three or
    four figures rather than one per concept or one per chapter.

    Authored HERE, at plan time, rather than during the turn. Segments 2..N are
    already written in a background thread the student never waits on, so a
    diagram costs nothing they can perceive. Doing the same work live would put
    4-10s inside a turn to save no wall clock at all.

    Never raises and never blocks the segment: a segment without a figure is a
    plainer lesson, a segment that failed to author is no lesson.
    """
    try:
        from app.drona.tutor import turn_works_an_example
    except Exception:
        return
    objective = str(segment.get("objective") or "")
    notes = str(segment.get("teaching_notes") or "")
    if not force and not turn_works_an_example(objective, notes):
        return
    try:
        from app.drona.diagram_author import author_diagram
        svg, reason = author_diagram(
            subject=subject,
            concept=f"{sub_title} — {objective}",
            # The EXAMPLE is the subject of the drawing, not the topic. This is
            # what makes it a figure beside a worked problem rather than a
            # chapter illustration.
            explanation=f"Draw the small figure for this specific worked example: {notes}",
            detail="simple",
            # Two attempts, not one. The collision check rejects a first draft
            # often enough that a single shot loses figures that a retry fixes —
            # observed immediately, on a segment whose labels overlapped. Nobody
            # is waiting on this thread, so the second attempt is free to the
            # student and the difference is a figure existing or not.
            attempts=2,
        )
        if svg:
            segment["example_diagram_svg"] = svg
            logger.info(f"🖼️ [SEGMENT DIAGRAM] '{objective[:44]}' ({len(svg)} chars)")
        else:
            logger.info(f"[SEGMENT DIAGRAM SKIPPED] '{objective[:44]}': {reason[:60]}")
    except Exception as exc:
        logger.warning(f"[SEGMENT DIAGRAM FAILED] {exc}")


# ── SLOT 1 of the board resolution order: a PRECOMPUTED WIDGET PAYLOAD ──────
#
# WHY THIS IS HERE AND NOT BEHIND A MIGRATION
# -------------------------------------------
# Slot 1 in `tutor.py` was blocked three times on "the storage does not
# exist". It does exist. `lesson_plans.plan_json` is `jsonb`
# (migrations/0005_drona.sql), the segment dict inside it is an open object,
# and `_attach_example_diagram` above already writes a whole SVG into it as
# `segment["example_diagram_svg"]`. A widget payload — three short fields —
# goes in exactly the same place, under a sibling key, with no DDL, no new
# column and no schema review. `validate_plan_json` checks named fields and
# ignores every other key, so nothing rejects it on the way back out.
#
# WHAT IS ASKED, AND WHAT IS NOT RE-DECIDED HERE
# ----------------------------------------------
# The single-widget block is `render_single_widget_block` — the SAME text the
# live path puts in its system message — so the widget's schema, its version
# and the "EMIT IT unless this segment genuinely has nothing to draw" bar are
# single-sourced. Only the OUTPUT ENVELOPE differs, because there is no board
# here to carry a `board_event`: precompute asks for a bare payload object.
# The envelope override is placed AFTER the block deliberately. v4 measured
# that whatever the model reads LAST about diagrams is what it does, and an
# opt-out read last produced zero diagrams in 40 turns.
#
# The gate is `sanitize_widget_payload`, called with the archetype id, and it
# is the ONLY gate. A second one written here would be the "two validators
# that drift" failure the registry docstring names.
#
# THREE OUTCOMES, AND THEY ARE STORED, NOT INFERRED
# -------------------------------------------------
# The recurring defect in this project is a check that PASSES on absent
# information. A segment with no `example_widget_payload` could mean the
# concept was never eligible, or that the model was asked and said no, or
# that it answered and the gate dropped it — three different facts that an
# absent key cannot tell apart, and the middle one is the only signal for
# where the archetype column is too coarse. So EVERY segment the fill touches
# gets `example_widget_precompute.status`, whether or not anything was asked.
WIDGET_PAYLOAD_KEY = "example_widget_payload"
WIDGET_PRECOMPUTE_KEY = "example_widget_precompute"

#: The terminal states of one precompute attempt. SIX, not two, because
#: "there is no payload on this segment" has six causes with six different
#: owners and an absent key tells them apart from nothing.
#:   not_asked   the column gave a verdict and it named no widget — `med`,
#:               `not_in_scope`, `none_symbolic`, or a `high` row naming
#:               something the client registry does not ship. AN ANSWER.
#:   unresolved  the column could not be consulted at all: the CSV was
#:               unreadable, or the concept/chapter read failed. NOT AN ANSWER,
#:               and the distinction is load-bearing — measured on the first
#:               Ecosystem run, one transient socket error made a whole
#:               concept's 8 segments look like a concept with no widget.
#:   stored      a payload passed the gate and is on the segment
#:   declined    the model was asked and judged this segment wants no picture
#:   rejected    the model answered and the gate dropped it
#:   error       the call itself failed; nobody judged anything
WIDGET_PRECOMPUTE_STATES = ("not_asked", "unresolved", "stored", "declined",
                            "rejected", "error")

#: Confidence values that mean the archetype table was never actually
#: consulted, as opposed to consulted and answering "no widget".
#: `concept_archetypes` is explicit that these are "we do not know", not
#: "not high", and slot 1 has to carry that distinction forward.
_ARCHETYPE_UNRESOLVED = ("table_unreadable", "lookup_error", "unjoinable")

#: Cap on the model's params object before it is even parsed. A payload is
#: three short fields; anything of this size is a runaway generation, not a
#: widget, and it would ride every plan read forever.
MAX_WIDGET_PAYLOAD_CHARS = 8000


def _widget_precompute_messages(widget_id: str, sub_title: str,
                                segment: Dict[str, Any]) -> List[Dict[str, str]]:
    """The one call. Block verbatim from the registry; envelope stated after it.

    `render_single_widget_block` refers to "the objective in [CURRENT SEGMENT]
    below", so the user message MUST carry a section by that name or the
    block's own instruction points at nothing. That is why the segment is
    rendered under that exact heading rather than a tidier one.
    """
    board = segment.get("board_content") or []
    board_lines = []
    for item in board[:12]:
        if isinstance(item, dict):
            board_lines.append(str(item.get("text") or item.get("latex") or "")[:200])
        else:
            board_lines.append(str(item)[:200])
    return [
        {"role": "system", "content": (
            "You are preparing the board for ONE segment of a lesson, ahead of "
            "time. There is no student waiting and no turn in progress; you are "
            "choosing the picture this segment will be taught with.\n\n"
            f"{render_single_widget_block(widget_id)}\n\n"
            "OUTPUT — this is a plan-time call, so there are no board_events and "
            "no `seq`. Reply with ONE JSON object and nothing else:\n"
            "  declining:  {\"decline\": \"<one line saying why this segment "
            "wants no picture>\"}\n"
            f"  drawing:    {{\"payload\": {{\"widget\": \"{widget_id}\", "
            f"\"version\": {WIDGET_VERSIONS.get(widget_id, 1)}, \"params\": "
            "{ … }}, \"caption\": \"one short line\"}\n"
            "Fill `params` from this segment's own content — the nodes, labels "
            "and values below, not a generic textbook example."
        )},
        {"role": "user", "content": (
            f"Subtopic: {sub_title}\n\n"
            f"[CURRENT SEGMENT]\n"
            f"  objective: {str(segment.get('objective') or '')[:600]}\n"
            f"  teaching_notes: {str(segment.get('teaching_notes') or '')[:1500]}\n"
            f"  board_content:\n" + "\n".join(f"    - {b}" for b in board_lines) +
            f"\n\nProduce the JSON object."
        )},
    ]


def _attach_widget_payload(segment: Dict[str, Any], archetype, chap_data: Dict[str, Any],
                           sub_title: str, subtopic_key: Optional[str] = None,
                           plan_id: Optional[str] = None) -> str:
    """Fill slot 1 for this segment, in place. Returns the status it recorded.

    Never raises: a segment without a precomputed payload is a segment the
    live path handles exactly as it does today. A segment that killed the
    background fill is a lesson that does not exist.
    """
    widget_id = getattr(archetype, "widget", None)
    confidence = getattr(archetype, "confidence", "unjoinable")
    why = getattr(archetype, "why", "")

    def _record(status: str, note: str, **extra) -> str:
        segment[WIDGET_PRECOMPUTE_KEY] = {
            "status": status,
            "widget": widget_id,
            "archetype_confidence": confidence,
            "archetype_version": ARCHETYPE_VERSION,
            "why": note[:300],
            **extra,
        }
        return status

    if not widget_id:
        # NOT the same as a decline, and the distinction is the whole point of
        # writing this key on every segment: nobody was asked anything here.
        # And "the column said no widget" is not the same as "the column could
        # not be read" — the first is an answer, the second is an absence
        # wearing an answer's clothes, which is the recurring defect here.
        return _record(
            "unresolved" if confidence in _ARCHETYPE_UNRESOLVED else "not_asked",
            why or "archetype names no registered widget")

    from app.drona.widget_registry import sanitize_widget_payload

    client = get_drona_client()
    model_name = get_model_name("tutor")
    t0 = time.time()
    try:
        res = client.chat.completions.create(
            model=model_name,
            messages=_widget_precompute_messages(widget_id, sub_title, segment),
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=2048,
            timeout=PLANNER_TIMEOUT_S,
            extra_body=_thinking_off(),
        )
    except Exception as exc:
        # Booked as a failure even though nothing usable came back. This runs
        # on the detached fill thread, which is exactly where a day of spend
        # went untraceable on 2026-08-15.
        record_call(model_name, "widget_payload", ok=False,
                    latency_ms=int((time.time() - t0) * 1000),
                    chapter_id=chap_data.get("id"), plan_id=plan_id,
                    subtopic_key=subtopic_key or sub_title, error=str(exc))
        logger.warning(f"[WIDGET PRECOMPUTE FAILED] {widget_id}: {str(exc)[:120]}")
        return _record("error", f"{type(exc).__name__}: {str(exc)[:120]}")

    record_call(model_name, "widget_payload", ok=True, res=res,
                latency_ms=int((time.time() - t0) * 1000),
                chapter_id=chap_data.get("id"), plan_id=plan_id,
                subtopic_key=subtopic_key or sub_title)

    raw = (res.choices[0].message.content or "")
    if len(raw) > MAX_WIDGET_PAYLOAD_CHARS:
        logger.warning(f"[WIDGET PRECOMPUTE OVERSIZE] {widget_id}: {len(raw)} chars")
        return _record("rejected", f"response {len(raw)} chars exceeds {MAX_WIDGET_PAYLOAD_CHARS}")
    try:
        answer = json.loads(strip_fences(raw))
    except Exception as exc:
        return _record("rejected", f"unparseable JSON: {str(exc)[:100]}")
    if not isinstance(answer, dict):
        return _record("rejected", "response is not a JSON object")

    # A declared decline, and the two shapes an answer can arrive in. The
    # envelope asks for `payload` at the top level; a model that answers in
    # the board_event shape it was shown by the reused block is still
    # answering, and reading it is parsing, not gate-widening — whatever comes
    # out still goes through sanitize_widget_payload untouched.
    raw_payload = answer.get("payload")
    if raw_payload is None:
        for evt in (answer.get("board_events") or []):
            if isinstance(evt, dict) and isinstance(evt.get("payload"), dict):
                raw_payload = evt["payload"]
                break
    if raw_payload is None:
        reason = str(answer.get("decline") or answer.get("reason") or "").strip()
        logger.info(f"[WIDGET PRECOMPUTE DECLINED] {widget_id} on "
                    f"'{str(segment.get('objective'))[:40]}': {reason[:80] or '(no reason given)'}")
        return _record("declined", reason or "no payload and no reason given")

    gated = sanitize_widget_payload(raw_payload, archetype_widget=widget_id)
    if not gated:
        # sanitize_widget_payload has already logged WHICH check failed.
        return _record("rejected", "failed sanitize_widget_payload")
    if gated["route"] != ROUTE_ARCHETYPE_HIGH:
        # It answered with a DIFFERENT widget than the column named. Live,
        # that is still drawable and is kept as `model_choice`. Stored on the
        # segment it would become a permanent, cached picture that no
        # classification chose, served ahead of the live path on every future
        # turn. Slot 1 stores only what path 1 actually produced.
        logger.warning(f"[WIDGET PRECOMPUTE OFF-ARCHETYPE] asked for {widget_id}, "
                       f"got {gated['payload']['widget']}; storing nothing")
        return _record("rejected",
                       f"answered with {gated['payload']['widget']}, not {widget_id}")

    segment[WIDGET_PAYLOAD_KEY] = gated["payload"]
    caption = str(answer.get("caption") or "").strip()[:200]
    logger.info(f"🧩 [WIDGET PRECOMPUTED] {widget_id} for "
                f"'{str(segment.get('objective'))[:44]}'")
    return _record("stored", f"high -> {widget_id}", route=gated["route"],
                   **({"caption": caption} if caption else {}))



def _attach_segment_board(segment: Dict[str, Any], chap_data: Dict[str, Any],
                          sub_title: str, archetype,
                          subtopic_key: Optional[str] = None,
                          plan_id: Optional[str] = None) -> str:
    """Slot 1 then slot 4 for one authored segment, in tier order. Returns the
    slot-1 status.

    THE DECLINE RULE, AND IT DIFFERS BETWEEN THE TWO PATHS ON PURPOSE.
    Live, a decline shows no picture: the model has just judged that this
    segment wants none, and appending a fallback would put back the picture it
    declined. HERE nobody is waiting, so a decline falls through to tier 3 —
    the segment gets an authored SVG it would not otherwise have had.

    The decline itself is NOT cached. Nothing is stored that would stop the
    live path asking again, and because slot 4 sits BELOW slot 2 in
    `resolve_board_slot`, the SVG this writes cannot suppress the live widget
    directive on any future turn of that segment.
    """
    status = _attach_widget_payload(segment, archetype, chap_data, sub_title,
                                    subtopic_key=subtopic_key, plan_id=plan_id)
    subject = chap_data.get("subject") or ""
    # Unchanged: a segment that works an example gets a figure for that
    # example, whatever slot 1 did. Slot 1 outranks it at serve time, so a
    # segment with both loses nothing.
    _attach_example_diagram(segment, subject, sub_title)
    if status in ("declined", "rejected", "error") and not segment.get("example_diagram_svg"):
        # `unresolved` is deliberately NOT in that list. A concept whose column
        # could not be read may still be a `high` concept, and burning a
        # diagram_author call per segment on a transient socket error is paying
        # for a failure. It regenerates: the plan is invalidated by
        # planner_code_sha and the live path still resolves the column per turn.
        _attach_example_diagram(segment, subject, sub_title, force=True)
    return status


def _author_segment(chap_data: Dict[str, Any], sub_title: str, outline: Dict[str, Any],
                    index: int, depth_block: str, plan_id: Optional[str] = None,
                    with_diagram: bool = False,
                    subtopic_key: Optional[str] = None,
                    archetype=None) -> Dict[str, Any]:
    """Authors one full segment. index is 0-based.

    `with_diagram` is False on the synchronous path that authors segment 1,
    because that call is the last thing between a student and the first spoken
    word — ~24s today, and a diagram call would add 5 to it. Segment 1 gets its
    figure in the background fill instead, well before the student has finished
    hearing the segment.
    """
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
    model_name = get_model_name("segment")
    for attempt in (1, 2):
        t0 = time.time()
        try:
            res = client.chat.completions.create(
                model=model_name,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=4096,
                timeout=PLANNER_TIMEOUT_S,
                extra_body=_thinking_off(),
            )
        except Exception as exc:
            # Recorded even though nothing usable came back: a call that threw
            # after the provider began work is still billed, and calls exactly
            # like this one were the invisible spend of 2026-08-15.
            record_call(model_name, "segment", ok=False, attempt=attempt,
                        latency_ms=int((time.time() - t0) * 1000),
                        chapter_id=chap_data.get("id"), plan_id=plan_id,
                        subtopic_key=subtopic_key or sub_title, error=str(exc))
            raise
        record_call(model_name, "segment", ok=True, attempt=attempt, res=res,
                    latency_ms=int((time.time() - t0) * 1000),
                    chapter_id=chap_data.get("id"), plan_id=plan_id,
                    subtopic_key=subtopic_key or sub_title)
        raw = res.choices[0].message.content or ""
        finish = getattr(res.choices[0], "finish_reason", None) or "?"

        # An EMPTY body and a body of the wrong SHAPE are different failures
        # with different owners, and under response_format=json_object they
        # look identical downstream: a degenerate generation returns "{}",
        # which parses cleanly and then reports "board_content=n/a" -- a
        # content complaint about a call that produced no content. The same
        # confusion cost a day on diagram_author, where an empty body was
        # reported as "does not start with <svg>".
        #
        # finish_reason is the field that separates them and nothing was
        # logging it. Carry it into every message below.
        if not raw.strip() or raw.strip() in ("{}", "[]"):
            last_err = (f"segment {index+1}: EMPTY response from {model_name} "
                        f"(finish_reason={finish}, {len(raw)} chars) -- this is a "
                        f"gateway/model failure, not a content-shape failure")
            logger.warning(f"⚠️ [SEGMENT EMPTY] {last_err} (attempt {attempt}/2)")
            # Recorded as NOT ok: an empty body is billed and useless, and
            # booking it ok=True is how spend hides inside a success rate.
            record_call(model_name, "segment", ok=False, attempt=attempt, res=res,
                        latency_ms=int((time.time() - t0) * 1000),
                        chapter_id=chap_data.get("id"), plan_id=plan_id,
                        subtopic_key=subtopic_key or sub_title, error=last_err)
            # Do NOT append an empty assistant turn: it teaches the retry
            # nothing and some gateways reject a message with empty content.
            continue

        try:
            seg = sanitize_double_escaped_latex(json.loads(strip_fences(raw)))
        except json.JSONDecodeError:
            seg = sanitize_double_escaped_latex(json.loads(repair_json_escapes(strip_fences(raw)), strict=False))
        # json_object mode sometimes wraps the object in a single key --
        # {"segment": {...}} -- which parses fine and then reports
        # "board_content=n/a", a content complaint about a segment that is
        # actually right there one level down. Measured: an EMPTY body cannot
        # produce that message (it raises out of the parse above), so a wrapper
        # or a literal {} is what the message has always meant.
        #
        # Unwrap only when it is unambiguous: exactly one key, a dict value,
        # and board_content inside it. Anything looser would start inventing
        # structure the model did not send.
        if isinstance(seg, dict) and "board_content" not in seg and len(seg) == 1:
            _only = next(iter(seg.values()))
            if isinstance(_only, dict) and "board_content" in _only:
                logger.info(f"[SEGMENT UNWRAP] segment {index+1}: unwrapped from {{{next(iter(seg))!r}: ...}}")
                seg = _only

        seg["id"] = index + 1
        bc = seg.get("board_content")
        cp = seg.get("checkpoint") or {}
        # Prompt asks for 9-12; accept 8 so a near-miss doesn't burn a retry.
        if isinstance(bc, list) and 8 <= len(bc) <= 12 and cp.get("question") and cp.get("model_answer") and cp.get("rubric"):
            if with_diagram:
                # Slot 1 AND slot 4, in that order. `with_diagram` is the
                # background-fill flag: it is False on the synchronous path
                # that authors segment 1, because that call is the last thing
                # between a student and the first spoken word. Segment 1 gets
                # both in the fill, minutes before it is finished being heard.
                _attach_segment_board(seg, chap_data, sub_title, archetype,
                                      subtopic_key=subtopic_key, plan_id=plan_id)
            return seg
        last_err = (f"segment {index+1}: board_content={len(bc) if isinstance(bc, list) else 'n/a'}, "
                    f"checkpoint keys={list(cp)}, finish_reason={finish}")
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
                             depth_block: str, subtopic_key: Optional[str] = None,
                             archetype=None) -> None:
    """Authors segments 2..N in parallel and writes the completed plan. Runs in a
    background thread while the student is being taught segment 1.

    This runs DETACHED: nothing awaits it and the HTTP response has already been
    returned, so every call it makes is spent before anything is persisted. On
    2026-08-15 that property made a day of planner spend untraceable. Two guards
    follow from it - a hard ceiling on how many segments may be authored, and a
    record written for the fan-out whatever the outcome.
    """
    from concurrent.futures import ThreadPoolExecutor
    total = len(outline["segments"])

    # An outline is validated at 6-9 segments before it reaches here, so a
    # larger `total` means the outline itself is malformed. Authoring against it
    # would bill one Pro-or-Flash call per phantom segment, in a thread nobody
    # is watching. Refuse instead: the plan stays partial and regenerates.
    if total > MAX_SEGMENTS_PER_PLAN:
        logger.error(
            f"❌ [PLAN FAN-OUT REFUSED] plan={plan_id[:8]} outline claims {total} segments, "
            f"ceiling is {MAX_SEGMENTS_PER_PLAN}. Authoring nothing rather than billing "
            f"{total - 1} calls against a malformed outline."
        )
        _mark_plan_failed(plan_id, f"fan-out refused: outline claims {total} segments, ceiling {MAX_SEGMENTS_PER_PLAN}")
        return

    # SLOT 1 INPUT, resolved ONCE for the whole plan. The archetype classifies
    # a CONCEPT, and a plan is one concept, so asking per segment would be the
    # same two indexed reads seven times over. Total by construction:
    # `concept_archetype_for_session` never raises, and an unreadable table
    # yields confidence "table_unreadable" rather than a concept that merely
    # looks non-high — which is the difference between "we asked and the answer
    # was no" and "we could not ask".
    #
    # Normally resolved by `create_plan_streaming` on the MAIN thread and handed
    # in. This function runs DETACHED, alongside a poller hammering the same
    # shared PostgREST client, and the first Ecosystem precompute run lost a
    # whole concept to a transient "Server disconnected" raised right here. The
    # fallback stays for direct callers and tests.
    if archetype is None:
        archetype = concept_archetype_for_session(chap_data.get("id"), subtopic_key)
    _unresolved = archetype.confidence in _ARCHETYPE_UNRESOLVED
    # WARNING, not info, when the column could not be consulted: with no verdict
    # every concept looks like a concept with no widget, slot 1 is silently
    # empty, and the run reports itself complete. That is the failure this
    # project keeps rediscovering, in its plainest form.
    (logger.warning if _unresolved else logger.info)(
        f"{'⚠️ ' if _unresolved else ''}[PLAN ARCHETYPE] plan={plan_id[:8]} {subtopic_key}: "
        f"{archetype.confidence}"
        f"{('->' + archetype.widget) if archetype.widget else ''} — {archetype.why[:80]}"
        + (" — slot 1 is UNRESOLVED for this plan, which is NOT the same as "
           "'this concept has no widget'." if _unresolved else "")
    )

    try:
        with ThreadPoolExecutor(max_workers=4) as ex:
            rest = list(ex.map(
                lambda i: _author_segment(chap_data, sub_title, outline, i, depth_block,
                                          plan_id, with_diagram=True,
                                          subtopic_key=subtopic_key,
                                          archetype=archetype),
                range(1, total),
            ))
        # Segment 1 skipped its board work to keep time-to-first-word at ~24s.
        # It gets it here, minutes before the student finishes hearing it.
        _attach_segment_board(first_segment, chap_data, sub_title, archetype,
                              subtopic_key=subtopic_key, plan_id=plan_id)

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
        # The per-plan slot-1 tally, stated rather than inferable. An absent
        # payload has three causes with three different owners and a count of
        # stored payloads alone cannot tell them apart.
        _tally = {s: 0 for s in WIDGET_PRECOMPUTE_STATES}
        for _s in plan_json["segments"]:
            _st = ((_s.get(WIDGET_PRECOMPUTE_KEY) or {}).get("status") or "not_asked")
            _tally[_st] = _tally.get(_st, 0) + 1
        logger.info(
            f"🧩 [WIDGET PRECOMPUTE] plan={plan_id[:8]} {subtopic_key} "
            f"widget={archetype.widget or '(none)'} arch={archetype.confidence} "
            f"segments={total} " + " ".join(f"{k}={v}" for k, v in _tally.items() if v)
        )
        logger.info(f"✅ [PLAN COMPLETE] plan={plan_id[:8]} all {total} segments authored and validated")
    except Exception as e:
        # The student keeps whatever segments exist; the plan stays 'partial' so
        # the next lookup regenerates rather than serving a half lesson as cached.
        logger.error(f"❌ [BACKGROUND PLAN FILL FAILED] plan={plan_id[:8]}: {e}")
        _mark_plan_failed(plan_id, f"background fill: {type(e).__name__}: {e}")


def create_plan_streaming(chapter_id: str, subtopic_key: str) -> Dict[str, Any]:
    """Authors the outline + segment 1, stores them, and returns immediately.
    Segments 2..N are authored in the background."""
    import threading

    # id is selected because record_call attributes planner spend by chapter.
    # It was omitted here, so every "outline" row ever written carried a null
    # chapter_id — the accounting looked wired up and recorded nothing usable.
    chap_res = supabase.table("chapters").select("id, name, subject").eq("id", chapter_id).execute()
    chap_data = chap_res.data[0] if chap_res.data else {"id": chapter_id, "name": "Chapter", "subject": "Physics"}
    sub_title = resolve_topic_title(chapter_id, subtopic_key)

    structure_block, depth_block, is_grounded, has_recorded_lesson = retrieve_dual_blocks(chapter_id, sub_title)

    # SLOT 1 input, read HERE — on the MAIN thread, beside the other indexed
    # reads above — and handed to the detached fill rather than read inside it.
    archetype = concept_archetype_for_session(chapter_id, subtopic_key)

    t0 = time.time()
    outline = _author_outline(chap_data, sub_title, subtopic_key, structure_block, depth_block)
    t_outline = time.time() - t0
    first_segment = _author_segment(chap_data, sub_title, outline, 0, depth_block,
                                    subtopic_key=subtopic_key)
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
        **plan_provenance(),
    }]).execute()
    if not ins.data:
        raise RuntimeError("Failed to insert streaming lesson plan")
    row = ins.data[0]

    threading.Thread(
        target=_fill_remaining_segments,
        args=(row["id"], chap_data, sub_title, outline, first_segment, depth_block,
              subtopic_key, archetype),
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
            # DEAD BEATS YOUNG. The grace window below asks "is this plan new
            # enough that the background thread might still be working?", which
            # is the right question only while the answer is unknowable. Since
            # _mark_plan_failed exists it IS knowable, and a failed plan inside
            # the window would otherwise be served with
            #
            #   [PLAN PARTIAL] ... still filling — segments arrive as authored
            #
            # to a student who would get 1 of 7 segments and wait forever for
            # the rest. Observed live on Maths 12 Ch8: a JSONDecodeError killed
            # the fill 33s in, well inside the 300s window.
            #
            # This is the same defect the harness had this morning, in the same
            # shape -- "not complete" read as "still going" -- and fixing it
            # there and not here just moved it from a script nobody watches to
            # a path a student walks.
            if plan_json.get(PLAN_STATUS_KEY) == "failed":
                logger.warning(
                    f"⚠️ [PLAN FAILED] '{subtopic_key}' background fill died "
                    f"({plan_json.get(PLAN_ERROR_KEY, 'no reason recorded')}). Regenerating."
                )
                try:
                    supabase.table("lesson_plans").delete().eq("id", cached_plan["id"]).execute()
                except Exception as del_err:
                    logger.error(f"Failed to delete failed plan: {del_err}")
                return create_plan_streaming(chapter_id, subtopic_key)

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

        # PROVENANCE CHECK -- the lazy invalidation of docs/plan-invalidation.md.
        #
        # 0033 added these columns and the planner WROTE them, but nothing ever
        # READ them: the cache hit tested only "is it still filling" and "does
        # it validate". So the cache key documented as
        #   (concept_id, planner_prompt_hash, planner_code_sha, model_id,
        #    archetype_version, chunk_corpus_version)
        # was in practice just (concept_id), and a plan authored by a different
        # planner, a different prompt or a different MODEL was served forever.
        # The columns made it look wired. That is the same shape as prompt_version
        # not covering the planner, and grounded always being true.
        #
        # Deliberately NOT compared: chunk_corpus_version. It is derived per call
        # from a live count over pdf_chunks, so with the corpus mid-rebuild every
        # lookup would differ from every stored value and NOTHING would ever cache.
        # Add it once the corpus is stable.
        #
        # planner_code_sha hashes the WHOLE file, so a comment or a log line
        # invalidates every plan. That is coarse, and deliberately coarse in the
        # safe direction: over-invalidating costs a regeneration, under-
        # invalidating serves a stale lesson forever. At 24 plans that is free.
        # Narrow it before the corpus fills, not after.
        _prov = plan_provenance()
        _drift = [
            (k, cached_plan.get(k), _prov[k])
            for k in ("planner_prompt_hash", "planner_code_sha", "model_id")
            if cached_plan.get(k) != _prov[k]
        ]
        if _drift:
            logger.warning(
                f"⚠️ [PLAN PROVENANCE DRIFT] '{subtopic_key}' regenerating — "
                + "; ".join(f"{k}: {was!r} -> {now!r}" for k, was, now in _drift)
            )
            try:
                supabase.table("lesson_plans").delete().eq("id", cached_plan["id"]).execute()
                return create_plan_streaming(chapter_id, subtopic_key)
            except Exception as regen_err:
                # Serve the stale plan rather than 500. Note this is a PARTIAL
                # mitigation: the delete above has already run, so the row is
                # gone and only this request still has the object.
                #
                # That is the bug the invalid-plan path below documents in its
                # own comment -- "Regenerate BEFORE deleting ... the cached plan
                # was already gone, so the student got a 500 and the plan was
                # destroyed permanently. Observed on two subtopics." -- except
                # that path ALSO deletes first and regenerates second, so the
                # comment describes a fix its code does not implement. Flagged,
                # not silently copied. Fixing it properly needs an insert that
                # can coexist with the old row (the unique key on
                # (chapter_id, subtopic_key) is why it was written this way),
                # which is a schema question, not a reordering.
                logger.error(f"Provenance regeneration failed, serving the stale plan: {regen_err}")
                return cached_plan

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
