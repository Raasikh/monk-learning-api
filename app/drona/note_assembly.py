"""Assembles a saveable note from a finished Drona session.

The board a student saw is authored content: `lesson_plans.plan_json` holds a
`board_content` array of 6-9 event objects per segment, and tutor.py emits those
objects verbatim (see its step 13 — the model is deliberately not allowed to
retype them). So the plan is the source of truth for *what* the board said.

`drona_turns` is the source of truth for *how much* of it the student actually
reached. A session abandoned in segment 2 of 9 must not produce a note holding
all nine segments — the same mistake the /end summary already had to fix.

This module reads only. It adds no behaviour to the live session path.
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.db import supabase

logger = logging.getLogger("drona.note_assembly")


class NoteAssemblyError(Exception):
    """Raised when a note cannot be assembled. Never swallowed into an empty note."""


def _as_dict(value: Any) -> Dict[str, Any]:
    """plan_json and raw_response are jsonb but arrive as str from some writers."""
    if isinstance(value, str):
        return json.loads(value)
    return value or {}


def _segment_reach(session_id: str) -> Tuple[Dict[int, int], int]:
    """How far the board got in each segment.

    Returns ({segment_index: highest board seq reached}, highest segment index).
    A segment the student passed through in full reports its top seq; the
    segment they stopped inside reports only what was written before they left.
    """
    turns_res = (
        supabase.table("drona_turns")
        .select("segment_index, raw_response, board_event_count")
        .eq("session_id", session_id)
        .order("turn_index")
        .execute()
    )
    turns = turns_res.data or []

    reach: Dict[int, int] = {}
    running: Dict[int, int] = {}
    max_segment = 0

    for turn in turns:
        seg = turn.get("segment_index")
        if not isinstance(seg, int):
            continue
        max_segment = max(max_segment, seg)

        events: List[Any] = []
        try:
            events = _as_dict(turn.get("raw_response")).get("board_events") or []
        except (json.JSONDecodeError, TypeError) as err:
            # A malformed raw_response costs us this turn's precision, not the
            # note. Say so rather than silently under-reporting the board.
            logger.warning(
                "Unparseable raw_response on session %s segment %s: %s",
                session_id, seg, err,
            )

        seqs = [e.get("seq") for e in events if isinstance(e, dict) and isinstance(e.get("seq"), int)]
        if seqs:
            reach[seg] = max(reach.get(seg, 0), max(seqs))
        else:
            # No seq numbers to trust (older turns, or a turn that recorded only
            # a count). Fall back to accumulating the per-turn counts, which is
            # how the tutor hands items out: consecutively, from the top.
            count = turn.get("board_event_count") or len(events)
            if count:
                running[seg] = running.get(seg, 0) + count
                reach[seg] = max(reach.get(seg, 0), running[seg])

    return reach, max_segment


def _flatten_board(board_items: List[Dict[str, Any]]) -> str:
    """Renders the board as readable text for `notes.content`.

    The note page shows `content` as a plain string, so the structured board
    needs a readable form alongside `board_items`. Formulas keep their LaTeX
    wrapped in $…$ so the same delimiters work if that text is ever fed through
    the KaTeX renderer.
    """
    lines: List[str] = []
    for group in board_items:
        if lines:
            lines.append("")
        lines.append(group["segment_title"])
        for item in group["items"]:
            latex = (item.get("latex") or "").strip()
            text = (item.get("text") or "").strip()
            if latex:
                lines.append(f"${latex}$")
            elif text:
                lines.append(text)
    return "\n".join(lines)


def _chapter_meta(chapter_id: Optional[str]) -> Dict[str, Optional[str]]:
    if not chapter_id:
        return {"chapter_name": None, "subject": None}
    res = (
        supabase.table("chapters")
        .select("name, subject, class_level")
        .eq("id", chapter_id)
        .execute()
    )
    if not res.data:
        return {"chapter_name": None, "subject": None}
    row = res.data[0]
    subject = (row.get("subject") or "").strip()
    return {
        "chapter_name": row.get("name"),
        "subject": subject.capitalize() or None,
    }


def assemble_session_note(session_id: str, user_id: str) -> Dict[str, Any]:
    """Builds the note payload for one session.

    Raises NoteAssemblyError when there is nothing honest to save — an unknown
    session, someone else's session, a session with no plan, or one where the
    board never got written. An empty note is not a successful save.
    """
    sess_res = (
        supabase.table("drona_sessions")
        .select("id, user_id, chapter_id, subtopic_key, plan_id, phase, "
                "current_segment, segments_completed, language, created_at")
        .eq("id", session_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not sess_res.data:
        raise NoteAssemblyError("Session not found")
    session = sess_res.data[0]

    plan_id = session.get("plan_id")
    if not plan_id:
        raise NoteAssemblyError(
            "This session never got a lesson plan, so it has no board to save."
        )

    plan_res = supabase.table("lesson_plans").select("plan_json").eq("id", plan_id).execute()
    if not plan_res.data:
        raise NoteAssemblyError("The lesson plan for this session is missing.")

    plan = _as_dict(plan_res.data[0].get("plan_json"))
    segments: List[Dict[str, Any]] = plan.get("segments") or []
    if not segments:
        raise NoteAssemblyError("The lesson plan for this session has no segments.")

    reach, max_turn_segment = _segment_reach(session_id)

    # How many segments to include. `segments_completed` is authoritative when
    # set; the turn log covers sessions that ended mid-segment, where the
    # student still saw part of a segment that was never marked complete.
    completed = session.get("segments_completed") or 0
    last_segment = max(completed, max_turn_segment, 0)
    if last_segment <= 0:
        raise NoteAssemblyError(
            "Nothing was written on the board in this session yet."
        )
    last_segment = min(last_segment, len(segments))

    board_items: List[Dict[str, Any]] = []
    segments_covered = 0

    for seg_index in range(1, last_segment + 1):
        segment = segments[seg_index - 1]
        content = segment.get("board_content") or []
        if not isinstance(content, list):
            continue

        # A segment below the last one was taught through to its checkpoint, so
        # its whole board was written. The last one is trimmed to what the
        # student actually reached.
        if seg_index < last_segment:
            reached = len(content)
        else:
            reached = reach.get(seg_index, 0)
            if reached <= 0:
                # Entered but nothing recorded — drop it rather than invent a
                # board the student never saw.
                continue

        kept = [
            item for item in content
            if isinstance(item, dict) and (item.get("seq") or 0) <= reached
        ]
        # Plans whose items carry no seq fall back to position.
        if not kept:
            kept = [item for item in content[:reached] if isinstance(item, dict)]
        if not kept:
            continue

        segments_covered += 1
        board_items.append({
            "segment_index": seg_index,
            "segment_title": segment.get("title") or segment.get("objective") or f"Part {seg_index}",
            "items": kept,
        })

    if not board_items:
        raise NoteAssemblyError(
            "Nothing was written on the board in this session yet."
        )

    meta = _chapter_meta(session.get("chapter_id"))
    topic = (plan.get("topic") or "").strip()
    item_count = sum(len(group["items"]) for group in board_items)

    # Keyed to the `notes` table exactly as the web pages read it: `concept` is
    # the title they render, `chapter` the chapter name, `content` the readable
    # board. `board_items` keeps the same board as structured events so it can
    # be re-rendered through the live session's board components.
    return {
        "user_id": user_id,
        "session_id": session_id,
        "chapter_id": session.get("chapter_id"),
        "subject": meta["subject"],
        "chapter": meta["chapter_name"],
        "concept": topic or meta["chapter_name"] or "Saved session",
        "content": _flatten_board(board_items),
        "board_items": board_items,
        "segments_covered": segments_covered,
        "total_segments": len(segments),
        "item_count": item_count,
        "session_started_at": session.get("created_at"),
    }


def structure_note_content(note: Dict[str, Any]) -> Optional[str]:
    """Rewrites the flat board dump into organised revision notes with gpt-4o-mini.

    The raw board is a faithful transcript of what was written, but it reads as
    a list of lines in teaching order — fine during class, weak as revision
    material. This pass groups it, orders it for review, and surfaces the key
    formulas and traps. Returns None on ANY failure so the caller keeps the
    honest flat content — a note must never fail to save because a
    restructuring call did.

    Plain text only: the note page renders `content` inside whitespace-pre-wrap
    with no markdown parser, so markdown syntax would show up literally.
    """
    import os
    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        client = OpenAI(api_key=api_key, timeout=25.0, max_retries=1)
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.3,
            max_tokens=1800,
            messages=[
                {"role": "system", "content": (
                    "You reorganise a class-11/12 lesson board transcript into clean revision notes.\n"
                    "Rules:\n"
                    "- PLAIN TEXT only. No markdown symbols (no #, *, **, backticks). They will be shown literally.\n"
                    "- Structure: a SECTION HEADING IN CAPS per topic, short bullet lines starting with '• ', "
                    "and formulas on their own lines kept EXACTLY as given (keep the $...$ delimiters untouched).\n"
                    "- End with a section 'QUICK REVISION' — the 3-6 most exam-relevant points/formulas.\n"
                    "- Keep every formula and every exam trap/mnemonic from the input. Do not invent new content. "
                    "Do not drop content — condense wording, never coverage.\n"
                    "- Same language as the input."
                )},
                {"role": "user", "content": (
                    f"Subject: {note.get('subject') or 'unknown'}\n"
                    f"Chapter: {note.get('chapter') or 'unknown'}\n"
                    f"Topic: {note.get('concept') or 'unknown'}\n\n"
                    f"Board transcript:\n{note.get('content') or ''}"
                )},
            ],
        )
        structured = (res.choices[0].message.content or "").strip()
        # A structuring pass that LOST material is worse than the flat dump.
        # Cheap sanity floor: it should not come back dramatically shorter
        # than the source.
        if not structured or len(structured) < 0.5 * len(note.get("content") or ""):
            logger.warning("Note structuring output too short — keeping flat board content.")
            return None
        return structured
    except Exception as err:
        logger.warning("Note structuring failed (%s) — keeping flat board content.", err)
        return None
