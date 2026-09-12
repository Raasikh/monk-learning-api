"""
progress_scoring — writes concept mastery from answer evidence (spec §4, §9, §15).

Called by the practice answer path AFTER grading, BEFORE the attempt row is
inserted (the first-attempt check counts prior attempts, so the current one
must not be in the table yet).

The rules enforced here:
  * Only a FIRST attempt on a question scores. Prior attempt → zero.
  * Burn-on-render: a question served to the student before this serve is
    burned — answering it later earns zero (spec §15).
  * Answer-time floor: under 4s (medium) / 8s (hard+) records but scores zero.
  * gain = g_base × Dq × (100−m)/100 ; loss = l_base × m/100 (spec §4.2)
  * secondary concepts receive secondary_concept_weight (0.35) of gain/loss.
  * mock answers get mock_multiplier (1.15).

Every constant comes from progress_config; nothing is hardcoded.
Scoring must never break grading — callers wrap this in try/except.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.db import supabase

logger = logging.getLogger(__name__)


def get_active_config() -> Dict[str, Any]:
    rows = supabase.table("progress_config").select("config").eq("active", True).limit(1).execute().data
    return rows[0]["config"] if rows else {}


def difficulty_band(raw_difficulty: Any, cfg: Dict[str, Any]) -> str:
    """questions.difficulty is numeric 1–5 (36% NULL). Map via config."""
    dmap = cfg.get("difficulty_map", {})
    key = "null" if raw_difficulty is None else str(raw_difficulty)
    return dmap.get(key, "medium")


def compute_mastery_updates(
    concept_roles: List[Tuple[str, str]],
    mastery_by_id: Dict[str, Dict[str, Any]],
    is_correct: bool,
    dq: float,
    cfg: Dict[str, Any],
    mode_mult: float = 1.0,
) -> List[Dict[str, Any]]:
    """Pure award math (spec §4.2/§4.3). Returns one update dict per concept."""
    g_base = float(cfg.get("g_base", 14))
    l_base = float(cfg.get("l_base", 5))
    sec_w = float(cfg.get("secondary_concept_weight", 0.35))
    strong = float(cfg.get("strong_threshold", 80))
    half_lives = cfg.get("half_lives_days", [21, 45, 90])

    updates = []
    for concept_id, role in concept_roles:
        row = mastery_by_id.get(concept_id) or {}
        m = float(row.get("mastery", 0))
        w = 1.0 if role == "primary" else sec_w
        if is_correct:
            gain = g_base * dq * (100 - m) / 100 * w * mode_mult
            new_m = min(100.0, m + gain)
        else:
            new_m = max(0.0, m - l_base * (m / 100) * w)

        proven = int(row.get("proven_count", 0))
        half_life = half_lives[min(proven, len(half_lives) - 1)]
        updates.append({
            "concept_id": concept_id,
            "role": role,
            "before": round(m, 2),
            "after": round(new_m, 2),
            "mastery": round(new_m, 2),
            "peak_mastery": round(max(float(row.get("peak_mastery", 0)), new_m), 2),
            "attempts_first": int(row.get("attempts_first", 0)) + 1,
            "correct_first": int(row.get("correct_first", 0)) + (1 if is_correct else 0),
            # a Strong concept enters the spaced-revision queue (spec §8)
            "reached_strong": new_m >= strong,
            "half_life_days": half_life,
        })
    return updates


def apply_answer_scoring(
    user_id: str,
    question_id: str,
    is_correct: bool,
    raw_difficulty: Any,
    mode: str = "practice",
) -> Optional[Dict[str, Any]]:
    """Full scoring pass for one graded answer. Returns a summary for the
    response payload, or None when the question has no concept tagging yet
    (subjects whose taxonomy hasn't been curated)."""
    cfg = get_active_config()
    now = datetime.now(timezone.utc)

    # concepts this question evidences
    qc = (
        supabase.table("question_concepts")
        .select("concept_id, role")
        .eq("question_id", question_id)
        .execute()
        .data
    )
    if not qc:
        return None

    # Retired concepts are dropped here, and loudly. A link left pointing at an
    # inactive concept fails SILENTLY otherwise: mastery is written normally,
    # but /progress filters that concept out of both the listing and the
    # chapter denominator, so the student earns a score that appears nowhere.
    # It happened for real — migrations 0022 and 0023 deactivated 18 misfiled
    # concepts and left 48 question links behind, and nothing surfaced it
    # because every step of the write path succeeded.
    active_ids = {
        r["id"] for r in (
            supabase.table("concepts")
            .select("id")
            .in_("id", [r["concept_id"] for r in qc])
            .eq("active", True)
            .execute()
            .data or []
        )
    }
    retired = [r["concept_id"] for r in qc if r["concept_id"] not in active_ids]
    if retired:
        logger.warning(
            f"[SCORING] question {question_id} is linked to {len(retired)} retired "
            f"concept(s) {retired}; skipping them. Remap the link — a retired "
            f"concept scores into a row no student can see."
        )
    concept_roles = [(r["concept_id"], r["role"]) for r in qc
                     if r["concept_id"] in active_ids]
    if not concept_roles:
        return {"scored": False, "reason": "all_concepts_retired", "concept_deltas": []}

    # ---- eligibility gates (spec §9.2 / §15) --------------------------------
    prior_attempts = (
        supabase.table("practice_attempts")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("question_id", question_id)
        .limit(0)
        .execute()
        .count
        or 0
    )

    serves = (
        supabase.table("question_serves")
        .select("id, served_at, answered_at")
        .eq("user_id", user_id)
        .eq("question_id", question_id)
        .order("served_at", desc=True)
        .limit(10)
        .execute()
        .data
    )
    open_serve = next((s for s in serves if not s.get("answered_at")), None)
    earlier_serves = [s for s in serves if open_serve and s["id"] != open_serve["id"]]

    time_ms: Optional[int] = None
    if open_serve:
        served_at = datetime.fromisoformat(open_serve["served_at"].replace("Z", "+00:00"))
        time_ms = int((now - served_at).total_seconds() * 1000)
        supabase.table("question_serves").update(
            {"answered_at": now.isoformat(), "time_to_answer_ms": time_ms}
        ).eq("id", open_serve["id"]).execute()

    band = difficulty_band(raw_difficulty, cfg)
    floor_ms = int(cfg.get("answer_time_floor_ms", {}).get(band, 4000))

    reason = None
    if prior_attempts > 0:
        reason = "repeat_attempt"          # burned the moment it was first answered
    elif earlier_serves:
        reason = "previously_served"       # burned the moment it first rendered
    elif time_ms is not None and time_ms < floor_ms:
        reason = "under_time_floor"        # guess or leak — recorded, not scored

    if reason:
        return {"scored": False, "reason": reason, "concept_deltas": []}

    # ---- award --------------------------------------------------------------
    dq = float(cfg.get("difficulty_multipliers", {}).get(band, 1.0))
    mode_mult = float(cfg.get("mock_multiplier", 1.15)) if mode == "mock" else 1.0

    existing = (
        supabase.table("concept_mastery")
        .select("concept_id, mastery, peak_mastery, attempts_first, correct_first, proven_count, flag_state")
        .eq("user_id", user_id)
        .in_("concept_id", [c for c, _ in concept_roles])
        .execute()
        .data
    )
    mastery_by_id = {r["concept_id"]: r for r in existing}

    updates = compute_mastery_updates(concept_roles, mastery_by_id, is_correct, dq, cfg, mode_mult)

    rows = []
    for u in updates:
        row = {
            "user_id": user_id,
            "concept_id": u["concept_id"],
            "mastery": u["mastery"],
            "peak_mastery": u["peak_mastery"],
            "attempts_first": u["attempts_first"],
            "correct_first": u["correct_first"],
            "half_life_days": u["half_life_days"],
            "last_evidence_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        if u["reached_strong"]:
            row["next_retest_at"] = (now + timedelta(days=u["half_life_days"])).isoformat()
        rows.append(row)
    supabase.table("concept_mastery").upsert(rows, on_conflict="user_id,concept_id").execute()

    return {
        "scored": True,
        "reason": None,
        "difficulty": band,
        "concept_deltas": [
            {"concept_id": u["concept_id"], "role": u["role"], "before": u["before"], "after": u["after"]}
            for u in updates
        ],
    }


def record_serve(user_id: str, question_id: str, context: str = "practice") -> None:
    """question.served — burns the item the instant it renders (spec §15)."""
    prior = (
        supabase.table("question_serves")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("question_id", question_id)
        .limit(0)
        .execute()
        .count
        or 0
    )
    supabase.table("question_serves").insert({
        "user_id": user_id,
        "question_id": question_id,
        "context": context,
        "first_serve": prior == 0,
    }).execute()
