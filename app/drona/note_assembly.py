"""Assembles a saveable note from a finished Drona session.

The board a student saw is authored content: `lesson_plans.plan_json` holds a
`board_content` array of 6-9 event objects per segment, and tutor.py emits those
objects verbatim (see its step 13 — the model is deliberately not allowed to
retype them). So the plan is the source of truth for *what* the board said.

`drona_turns` is the source of truth for *how much* of it the student actually
reached. The note carries the FULL lesson either way — ending early must not
cost the student their revision material — with the class-end boundary marked
so covered and yet-to-come segments stay distinguishable. What actually
happened in the session (minutes, questions answered) is the /end summary's
job, not the note's.

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


# Divider written into the flat content where the live class stopped. The
# structuring pass keys off it to split covered material from what remains.
CLASS_END_MARKER = "——— class ended here — everything below is the rest of the lesson, for self-study ———"


def _flatten_board(board_items: List[Dict[str, Any]]) -> str:
    """Renders the board as readable text for `notes.content`.

    The note page shows `content` as a plain string, so the structured board
    needs a readable form alongside `board_items`. Formulas keep their LaTeX
    wrapped in $…$ so the same delimiters work if that text is ever fed through
    the KaTeX renderer.
    """
    lines: List[str] = []
    marker_written = False
    for group in board_items:
        if not group.get("covered", True) and not marker_written and lines:
            lines.append("")
            lines.append(CLASS_END_MARKER)
            marker_written = True
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

    # How far the CLASS got. The note now always carries the FULL lesson —
    # a student who ends early still gets complete revision notes for the
    # topic — and this boundary only marks where the live class stopped, so
    # covered and yet-to-come material stay distinguishable. (The /end summary
    # is the record of what actually happened; the note is the study
    # material.)
    completed = session.get("segments_completed") or 0
    last_segment = min(max(completed, max_turn_segment, 0), len(segments))

    board_items: List[Dict[str, Any]] = []
    segments_covered = 0

    for seg_index in range(1, len(segments) + 1):
        segment = segments[seg_index - 1]
        content = segment.get("board_content") or []
        if not isinstance(content, list):
            continue

        kept = [item for item in content if isinstance(item, dict)]
        if not kept:
            continue

        covered = seg_index <= last_segment
        if covered:
            segments_covered += 1
        board_items.append({
            "segment_index": seg_index,
            "segment_title": segment.get("title") or segment.get("objective") or f"Part {seg_index}",
            "covered": covered,
            "items": kept,
        })

    if not board_items:
        raise NoteAssemblyError(
            "The lesson plan for this session has no board content to save."
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


def _structure_text(client: Any, subject: str, chapter: str, topic: str,
                    text: str, quick_revision: bool) -> Optional[str]:
    """One gpt-4o-mini structuring pass over one block of board transcript."""
    tail_rule = (
        "- End with a section 'QUICK REVISION' — the 3-6 most exam-relevant points/formulas.\n"
        if quick_revision else
        "- Do NOT add a QUICK REVISION or summary section.\n"
    )
    res = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.3,
        max_tokens=2400,
        messages=[
            {"role": "system", "content": (
                "You reorganise a class-11/12 lesson board transcript into clean revision notes.\n"
                "Rules:\n"
                "- PLAIN TEXT only. No markdown symbols (no #, *, **, backticks). They will be shown literally.\n"
                "- Structure: a SECTION HEADING IN CAPS per topic, short bullet lines starting with '• ', "
                "and formulas on their own lines kept EXACTLY as given (keep the $...$ delimiters untouched).\n"
                f"{tail_rule}"
                "- Keep every formula and every exam trap/mnemonic from the input. Do not invent new content. "
                "Do not drop content — condense wording, never coverage.\n"
                "- Same language as the input."
            )},
            {"role": "user", "content": (
                f"Subject: {subject}\nChapter: {chapter}\nTopic: {topic}\n\n"
                f"Board transcript:\n{text}"
            )},
        ],
    )
    structured = (res.choices[0].message.content or "").strip()
    # A structuring pass that LOST material is worse than the flat dump.
    # Cheap sanity floor: it should not come back dramatically shorter than
    # the source.
    if not structured or len(structured) < 0.5 * len(text):
        return None
    return structured


def structure_note_content(note: Dict[str, Any]) -> Optional[str]:
    """Rewrites the flat board dump into organised revision notes with gpt-4o-mini.

    The raw board is a faithful transcript of what was written, but it reads as
    a list of lines in teaching order — fine during class, weak as revision
    material. This pass groups it, orders it for review, and surfaces the key
    formulas and traps. Returns None on ANY failure so the caller keeps the
    honest flat content — a note must never fail to save because a
    restructuring call did.

    The covered and not-yet-covered halves of an early-ended session are
    structured in SEPARATE calls. A single call with a "keep these apart"
    instruction measurably blended the unreached segments into the main
    sections and left the self-study section reading "None".

    Plain text only: the note page renders `content` inside whitespace-pre-wrap
    with no markdown parser, so markdown syntax would show up literally.
    """
    import os
    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        client = OpenAI(api_key=api_key, timeout=45.0, max_retries=1)

        subject = note.get("subject") or "unknown"
        chapter = note.get("chapter") or "unknown"
        topic = note.get("concept") or "unknown"
        flat = note.get("content") or ""

        covered_text, _, remaining_text = flat.partition(CLASS_END_MARKER)
        covered_text = covered_text.strip()
        remaining_text = remaining_text.strip()

        # Both halves in parallel: a full 9-segment self-study half measurably
        # blew a sequential 25s budget, and the student is watching a spinner
        # on "Save board to notes" the whole time.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_covered = pool.submit(
                _structure_text, client, subject, chapter, topic, covered_text, True
            ) if covered_text else None
            fut_rest = pool.submit(
                _structure_text, client, subject, chapter, topic, remaining_text, False
            ) if remaining_text else None

            parts: List[str] = []
            if fut_covered is not None:
                structured = fut_covered.result()
                if structured is None:
                    logger.warning("Note structuring output too short — keeping flat board content.")
                    return None
                parts.append(structured)
            if fut_rest is not None:
                structured_rest = fut_rest.result()
                if structured_rest is None:
                    logger.warning("Note structuring (self-study half) too short — keeping flat board content.")
                    return None
                parts.append("NOT COVERED IN CLASS YET — SELF-STUDY\n\n" + structured_rest)

        return "\n\n\n".join(parts) if parts else None
    except Exception as err:
        logger.warning("Note structuring failed (%s) — keeping flat board content.", err)
        return None
