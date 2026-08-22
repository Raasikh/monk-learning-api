"""What Drona knows about THIS student before the lesson starts.

The tutor's `understanding_signal` is computed from drona_turns filtered to the
current session, so every lesson opened amnesiac: a student could have been
flagged on escape velocity last week and Drona would teach it as if for the
first time. The Progress feature already stores the durable picture
(concept_mastery, student_misconceptions); nothing read it back into a lesson.

Everything here is CHAPTER-SCOPED on purpose. A student sitting down to
Gravitation should not hear about their weak concepts in Current Electricity —
that is noise at best and discouraging at worst. `concepts.chapter_id` makes
the filter exact rather than heuristic.
"""
import logging
from typing import Any, Dict, List, Optional

from app.db import supabase

logger = logging.getLogger("drona.student_context")

# Mirrors progress_config v1 so a concept called "weak" here is the same one the
# Progress page calls weak. If those constants move, move these with them.
STRONG_THRESHOLD = 80
IMPROVING_THRESHOLD = 45

MAX_WEAK = 5
MAX_STRONG = 3
MAX_MISCONCEPTIONS = 4


def load_prior_knowledge(user_id: str, chapter_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Returns this student's durable history for ONE chapter, or None.

    None means "teach this fresh" — no history, no chapter, or a failed
    lookup. A missing signal must never be worse than the old amnesiac
    behaviour, so every failure path here degrades to None rather than raising.
    """
    if not user_id or not chapter_id:
        return None

    try:
        concept_res = (
            supabase.table("concepts")
            .select("id, name")
            .eq("chapter_id", chapter_id)
            .eq("active", True)
            .execute()
        )
        concepts = {c["id"]: c["name"] for c in (concept_res.data or [])}
        if not concepts:
            return None

        mastery_res = (
            supabase.table("concept_mastery")
            .select("concept_id, mastery, flag_state, last_evidence_at")
            .eq("user_id", user_id)
            .in_("concept_id", list(concepts.keys()))
            .execute()
        )
        rows = mastery_res.data or []
    except Exception as err:
        logger.warning(f"[PRIOR KNOWLEDGE] mastery lookup failed for chapter {chapter_id}: {err}")
        return None

    weak: List[Dict[str, Any]] = []
    strong: List[Dict[str, Any]] = []
    for r in rows:
        name = concepts.get(r.get("concept_id"))
        if not name:
            continue
        try:
            score = float(r.get("mastery") or 0)
        except (TypeError, ValueError):
            continue
        flagged = (r.get("flag_state") or "") == "flagged"
        # A flagged concept counts as weak whatever its score — the flag exists
        # precisely to catch decay that the raw number hasn't caught up with.
        if flagged or score < IMPROVING_THRESHOLD:
            weak.append({"name": name, "mastery": round(score), "flagged": flagged})
        elif score >= STRONG_THRESHOLD:
            strong.append({"name": name, "mastery": round(score)})

    # Weakest first, and flagged ahead of merely-low: those are the ones worth
    # spending a lesson's limited callback budget on.
    weak.sort(key=lambda c: (not c["flagged"], c["mastery"]))
    strong.sort(key=lambda c: -c["mastery"])

    misconceptions: List[str] = []
    try:
        mis_res = (
            supabase.table("student_misconceptions")
            .select("tag_canonical, tag_raw, created_at")
            .eq("user_id", user_id)
            .eq("chapter_id", chapter_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        for m in (mis_res.data or []):
            tag = (m.get("tag_canonical") or m.get("tag_raw") or "").strip()
            if tag and tag not in misconceptions:
                misconceptions.append(tag)
            if len(misconceptions) >= MAX_MISCONCEPTIONS:
                break
    except Exception as err:
        logger.warning(f"[PRIOR KNOWLEDGE] misconception lookup failed: {err}")

    if not weak and not strong and not misconceptions:
        return None

    return {
        "studied_before": True,
        "weak_concepts": weak[:MAX_WEAK],
        "strong_concepts": strong[:MAX_STRONG],
        "past_misconceptions": misconceptions,
    }
