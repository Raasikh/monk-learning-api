"""
/progress — everything the Progress page renders, in one call.

The response mirrors the page's blocks 1:1 (see the static build in
monk-learning-web src/app/progress/page.tsx): monk_score card, subject cards,
chapter/concept diagnosis, pace, recommendations, ledger. The frontend's job
is substitution, not computation.

All math follows the Progress spec. Constants come from progress_config
(active row) — never hardcoded here. Launch posture ("simple setup"):
 * chapter weights fall back to 1.0 until chapter_exam_weights is researched,
   so subjects are plain concept-mastery means for now;
 * pace is display-only and null until question_serves has timing data;
 * the climb bar / weekly delta read progress_snapshots (empty until the
   nightly job ships) and degrade to a flat series / +0.

Mastery lives in concept_mastery, written by the practice answer path.
Absence of a row = Not started (m = 0, no attempts) per spec §8.
"""

from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends

from app.auth import get_current_user_id
from app.db import supabase

router = APIRouter(prefix="/progress", tags=["progress"])

SUBJECTS_BY_EXAM = {
    "jee": ["physics", "chemistry", "mathematics"],
    "neet": ["physics", "chemistry", "biology"],
}


def _fetch_all(table: str, select: str, page: int = 1000, **filters) -> List[Dict[str, Any]]:
    """Supabase caps responses at 1000 rows; page through."""
    rows: List[Dict[str, Any]] = []
    off = 0
    while True:
        q = supabase.table(table).select(select).range(off, off + page - 1)
        for k, v in filters.items():
            q = q.eq(k, v)
        batch = q.execute().data
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page:
            break
        off += page
    return rows


def get_active_config() -> Dict[str, Any]:
    rows = supabase.table("progress_config").select("config").eq("active", True).limit(1).execute().data
    return rows[0]["config"] if rows else {}


def concept_state(mastery: float, flagged: bool, attempts: int, cfg: Dict[str, Any]) -> str:
    """Spec §8 — presentation state over the continuous mastery value."""
    if flagged:
        return "needs_revision"
    if attempts == 0 and mastery == 0:
        return "not_started"
    if mastery >= cfg.get("strong_threshold", 80):
        return "strong"
    if mastery >= cfg.get("improving_threshold", 45):
        return "improving"
    return "needs_revision" if attempts > 0 else "not_started"


@router.get("")
def get_progress(user_id: str = Depends(get_current_user_id), exam: Optional[str] = None):
    cfg = get_active_config()

    # The exam is an ENTITLEMENT, not a preference: it's what the student paid
    # for, written to profiles.target_exam at onboarding/purchase ('JEE',
    # 'NEET', or 'both'). Progress always scores against the entitled exam.
    # The ?exam= param only selects a view for 'both'-entitled students.
    prof = supabase.table("profiles").select("target_exam").eq("id", user_id).limit(1).execute().data
    raw = str((prof[0].get("target_exam") if prof else "") or "").strip().lower()
    entitlement = "both" if "both" in raw else ("neet" if "neet" in raw else "jee")
    allowed = ("jee", "neet") if entitlement == "both" else (entitlement,)
    requested = str(exam or "").strip().lower()
    exam = requested if requested in allowed else allowed[0]
    subjects = SUBJECTS_BY_EXAM[exam]
    subject_marks = cfg.get("subject_marks", {}).get(exam, {s: 1 for s in subjects})

    # syllabus skeleton: chapters + concepts (complete regardless of student)
    chapters = _fetch_all("chapters", "id, name, subject, class_level")
    chapters = [c for c in chapters if str(c["subject"]).lower() in subjects]
    concepts = _fetch_all("concepts", "id, chapter_id, name, display_order, exams")
    concepts = [c for c in concepts if exam in (c.get("exams") or ["jee", "neet"])]
    concepts_by_ch: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for c in concepts:
        concepts_by_ch[c["chapter_id"]].append(c)

    # exam-mark weights; 1.0 fallback until chapter_exam_weights is researched
    weights = {w["chapter_id"]: float(w["avg_marks"])
               for w in _fetch_all("chapter_exam_weights", "chapter_id, exam, avg_marks")
               if w.get("exam") == exam}

    # the student's evidence
    mastery_rows = _fetch_all(
        "concept_mastery",
        "concept_id, mastery, attempts_first, correct_first, flag_state, flagged_at",
        user_id=user_id,
    )
    m_by_concept = {r["concept_id"]: r for r in mastery_rows}
    flagged = [r for r in mastery_rows if r["flag_state"] == "flagged"]

    # ---- layers 1–4 ---------------------------------------------------------
    subject_payload = []
    subject_scores: Dict[str, float] = {}
    all_chapter_rows: List[Dict[str, Any]] = []

    for subj in subjects:
        subj_chapters = [ch for ch in chapters if str(ch["subject"]).lower() == subj]
        num = den = 0.0
        chapter_payload = []
        for ch in sorted(subj_chapters, key=lambda c: (c["class_level"], c["name"])):
            clist = sorted(concepts_by_ch.get(ch["id"], []), key=lambda c: c.get("display_order", 99))
            concept_payload = []
            m_sum = 0.0
            ch_flagged = ch_attempted = False
            for c in clist:
                m = m_by_concept.get(c["id"], {})
                mastery = float(m.get("mastery", 0))
                attempts = int(m.get("attempts_first", 0))
                is_flagged = m.get("flag_state") == "flagged"
                ch_flagged = ch_flagged or is_flagged
                ch_attempted = ch_attempted or attempts > 0
                m_sum += mastery
                concept_payload.append({
                    "concept_id": c["id"],
                    "name": c["name"],
                    "mastery": round(mastery, 1),
                    "state": concept_state(mastery, is_flagged, attempts, cfg),
                })
            m_ch = (m_sum / len(clist)) if clist else 0.0
            w_ch = weights.get(ch["id"], 1.0)
            num += m_ch * w_ch
            den += w_ch
            # chapter chip per §8: any flagged concept forces needs_revision;
            # fully untouched chapter shows not_started, never a 0% needs_revision
            if ch_flagged:
                state = "needs_revision"
            elif not ch_attempted:
                state = "not_started"
            else:
                state = concept_state(m_ch, False, 1, cfg)
            row = {
                "chapter_id": ch["id"],
                "name": ch["name"],
                "class_level": ch["class_level"],
                "subject": subj,
                "mastery": round(m_ch, 1),
                "weight_marks": w_ch if ch["id"] in weights else None,
                "state": state,
                "headroom": round(w_ch * (100 - m_ch) / 100, 2),
                "concepts": concept_payload,
                "curated": bool(clist),
            }
            chapter_payload.append(row)
            all_chapter_rows.append(row)
        s_sub = 10 * num / den if den else 0.0
        subject_scores[subj] = s_sub
        subject_payload.append({
            "subject": subj,
            "score": round(s_sub),
            "chapters": chapter_payload,
        })

    total_marks = sum(subject_marks.get(s, 1) for s in subjects) or 1
    ms_raw = sum(subject_scores[s] * subject_marks.get(s, 1) for s in subjects) / total_marks
    ceiling = 1000 - cfg.get("flag_ceiling_penalty", 18) * len(flagged)

    # snapshots power running-max, delta and the climb series; degrade gracefully
    snaps = (
        supabase.table("progress_snapshots")
        .select("snapshot_date, monk_score_display, monk_score_raw")
        .eq("user_id", user_id)
        .order("snapshot_date", desc=True)
        .limit(60)
        .execute()
        .data
    )
    running_max = max([ms_raw] + [float(s["monk_score_raw"]) for s in snaps])
    ms_display = min(running_max, ceiling)
    week_ago = next((float(s["monk_score_display"]) for s in snaps[6:7]), None)
    delta_week = round(ms_display - week_ago) if week_ago is not None else 0

    # ---- ledger (spec §13: plain lifetime totals, deliberately last) --------
    attempts = supabase.table("practice_attempts").select("id", count="exact").eq("user_id", user_id).limit(0).execute().count or 0
    doubts = supabase.table("doubts").select("id", count="exact").eq("user_id", user_id).eq("solved", True).limit(0).execute().count or 0
    strong_t = cfg.get("strong_threshold", 80)
    concepts_mastered = sum(1 for r in mastery_rows if float(r["mastery"]) >= strong_t and r["flag_state"] != "flagged")
    chapters_strong = sum(1 for r in all_chapter_rows if r["mastery"] >= strong_t and r["state"] != "needs_revision")

    # ---- recommendations (three roles, spec §12) ----------------------------
    curated = [r for r in all_chapter_rows if r["curated"]]
    best = max(curated, key=lambda r: r["headroom"], default=None)
    recs: List[Dict[str, Any]] = []
    if best:
        recs.append({
            "role": "highest_lever",
            "title": f"Practice {best['name']}",
            "subject": best["subject"],
            "chapter_id": best["chapter_id"],
            "reason": "Most score headroom available right now.",
        })
    if flagged:
        oldest = min(flagged, key=lambda r: r.get("flagged_at") or "9999")
        c_meta = next((c for c in concepts if c["id"] == oldest["concept_id"]), None)
        if c_meta:
            # persona-neutral: the tutor's display name (Drona/Veda) follows the
            # client's voice preference, which only the frontend knows.
            recs.append({
                "role": "clear_flag",
                "title": f"Refresh {c_meta['name']}",
                "concept_id": c_meta["id"],
                "reason": "Oldest revision flag — clearing it lifts your score cap.",
            })
    # pace card needs timing data; until then the third card is a mock rec
    recs.append({
        "role": "exam_craft",
        "title": "Take a mock test",
        "reason": "Mock answers earn a 1.15× exam-conditions premium.",
    })

    return {
        "exam": exam,
        "entitlement": entitlement,
        "monk_score": {
            "display": round(ms_display),
            "raw": round(ms_raw, 1),
            "ceiling": round(ceiling),
            "delta_week": delta_week,
            "flagged_concepts": len(flagged),
            "climb": [
                {"date": s["snapshot_date"], "score": round(float(s["monk_score_display"]))}
                for s in reversed(snaps)
            ],
        },
        "subjects": subject_payload,
        "pace": {"available": False, "note": "Display only — doesn't move your score yet."},
        "recommendations": recs,
        "ledger": {
            "doubts_solved": doubts,
            "questions_attempted": attempts,
            "concepts_mastered": concepts_mastered,
            "chapters_strong": chapters_strong,
        },
    }
