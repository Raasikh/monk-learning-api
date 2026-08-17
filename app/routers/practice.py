import json
import random
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import get_current_user_id
from app.db import supabase
from app.drona.persona import normalize_language, normalize_voice, tutor_name
from app.progress_scoring import apply_answer_scoring, record_serve


def resolve_display_concept(question_id: str, raw_concept: Optional[str]) -> Optional[str]:
    """The name shown during practice must match what Progress scores and
    displays for the same question — otherwise a student sees one concept
    name while answering and a different one on their Progress page for the
    identical question. Resolves through question_concepts (primary role) to
    the curated concepts.name; falls back to the legacy free-text tag for
    subjects not yet curated, so nothing breaks for them."""
    try:
        qc = (
            supabase.table("question_concepts")
            .select("concept_id")
            .eq("question_id", question_id)
            .eq("role", "primary")
            .limit(1)
            .execute()
            .data
        )
        if qc:
            row = supabase.table("concepts").select("name").eq("id", qc[0]["concept_id"]).limit(1).execute().data
            if row:
                return row[0]["name"]
    except Exception as e:
        print(f"[CONCEPT RESOLVE ERROR] {e}")
    return raw_concept

router = APIRouter(prefix="/practice", tags=["practice"])


# --- Request & Response Models ---

class PracticeNextRequest(BaseModel):
    exam: Optional[str] = "both"         # "jee", "neet", "both"
    class_level: Optional[str] = "both"  # "11", "12", "both"
    subject: Optional[str] = None        # Optional override for legacy callers


class PracticeAnswerRequest(BaseModel):
    question_id: str
    chosen_option: Optional[str] = None
    chosen_value: Optional[float] = None


class PracticeExplainRequest(BaseModel):
    question_id: str
    chosen_option: Optional[str] = None
    chosen_value: Optional[float] = None
    language: Optional[str] = None
    voice: Optional[str] = None


# --- Helper Functions ---

PLACEHOLDER_OPTIONS = {'A': 'Option A', 'B': 'Option B', 'C': 'Option C', 'D': 'Option D'}

# --- Numerical grading tolerance -------------------------------------------
# `value_tolerance` on the row is authoritative when set. Nothing has ever
# populated it with a usable value: measured 2026-08-10 against production, it
# is 0 on 377 of the 383 servable numerical rows and NULL on the other 6. Zero
# fails the `> 0` guard below just as NULL does, so the fallback still decides
# every numerical grade in production today. Do not read "tolerance is set" as
# "a per-row tolerance is in force" -- check that it is greater than zero.
#
#   accept  <=>  abs(given - key) <= max(NUMERIC_ABS_FLOOR, abs(key) * NUMERIC_REL_FRACTION)
#
# A purely ABSOLUTE tolerance cannot work across this corpus. Measured range of
# correct_value over the 390 non-null servable numerical rows: min 0 (11 rows are
# exactly 0), smallest non-zero 0.06, median 10, max 65544. The previous
# hardcoded 1e-3 rejected a student answer of 9.8 against a key of 9.81.
#
# 0.5% is the tightest relative band that still absorbs 2-3 significant-figure
# rounding. The absolute floor only binds when the key is exactly 0.
#
# For INTEGER-valued keys at or above 200, an unbounded 0.5% band would exceed 1
# and start accepting the adjacent integer (201 against a key of 200). Those keys
# are capped at 0.5 so neighbouring integers stay distinct. The cap is bounded
# above by NUMERIC_INT_CAP_MAX because at very large magnitudes integer adjacency
# is not a meaningful distinction -- 6.02e23 is integer-valued as a float, and
# capping it at 0.5 would demand an exact match to 24 significant figures.
NUMERIC_REL_FRACTION = 0.005   # 0.5%
NUMERIC_ABS_FLOOR = 1e-6
NUMERIC_INT_CAP = 0.5
NUMERIC_INT_CAP_MIN = 200
NUMERIC_INT_CAP_MAX = 1e6      # corpus max is 65544, so every live row is covered


def grade_numerical(given: float, key: float, tolerance: Optional[float] = None) -> bool:
    """True when `given` matches `key`.

    Uses the per-row `value_tolerance` when it is present and positive;
    otherwise falls back to a relative band, capped for large integer keys.
    """
    given = float(given)
    key = float(key)
    if tolerance is not None and float(tolerance) > 0:
        return abs(given - key) <= float(tolerance)

    tol = max(NUMERIC_ABS_FLOOR, abs(key) * NUMERIC_REL_FRACTION)
    if NUMERIC_INT_CAP_MIN <= abs(key) < NUMERIC_INT_CAP_MAX and key.is_integer():
        tol = min(tol, NUMERIC_INT_CAP)
    return abs(given - key) <= tol


def is_quality_question(q: Dict[str, Any]) -> bool:
    """Quality Filter Rule (GATE 8.6): Exclude corrupt or low-quality rows."""
    text = (q.get("question_text") or "").strip()
    if len(text) < 20:
        return False

    q_type = q.get("question_type")
    opts = q.get("options") or {}
    
    opt_dict = {}
    if isinstance(opts, dict):
        opt_dict = {str(k).strip(): str(v).strip() for k, v in opts.items()}
    elif isinstance(opts, list):
        opt_dict = {str(i): str(v).strip() for i, v in enumerate(opts)}

    if opt_dict == PLACEHOLDER_OPTIONS:
        return False

    if q_type == "single_correct":
        non_empty = [v for v in opt_dict.values() if v]
        if len(non_empty) < 4:
            return False

    return True


def matches_exam(target_exams_val: Any, selected_exam: str) -> bool:
    """Checks if question matches selected exam mode."""
    if selected_exam == "both":
        return True
    
    if not target_exams_val:
        return False

    if isinstance(target_exams_val, str):
        try:
            exams_list = json.loads(target_exams_val)
        except Exception:
            exams_list = [target_exams_val]
    else:
        exams_list = target_exams_val

    exams_lower = [str(e).lower() for e in exams_list]
    
    if selected_exam == "jee":
        return any("jee" in e for e in exams_lower)
    elif selected_exam == "neet":
        return any("neet" in e for e in exams_lower)

    return True


# --- Endpoints ---

@router.post("/next")
def get_next_question(
    req: PracticeNextRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Selects 1 exam-based practice question following GATE 8 rules:
    - Exam-based weighted subject distribution (JEE, NEET, Both)
    - 21-attempt repeat spacing logic & prioritization of wrong attempts
    - Strict Quality Filter (GATE 8.6)
    """
    exam_mode = (req.exam or "both").strip().lower()
    if exam_mode not in ["jee", "neet", "both"]:
        exam_mode = "both"

    class_req = (req.class_level or "both").strip().lower()
    if class_req not in ["11", "12", "both"]:
        class_req = "both"

    # 1. Subject Selection via Weighted Random Distribution (GATE 8.3)
    target_discipline: Optional[str] = None

    if req.subject: # Legacy override if specifically provided
        chosen_subject = req.subject.strip().lower()
        if chosen_subject in ["math", "maths"]:
            chosen_subject = "mathematics"
    elif exam_mode == "jee":
        chosen_subject = random.choices(["physics", "chemistry", "mathematics"], weights=[0.333, 0.333, 0.334])[0]
    elif exam_mode == "neet":
        chosen_subject = random.choices(["biology", "chemistry", "physics"], weights=[0.50, 0.25, 0.25])[0]
        if chosen_subject == "biology":
            target_discipline = random.choices(["botany", "zoology"], weights=[0.50, 0.50])[0]
    else: # Both
        chosen_subject = random.choices(["physics", "chemistry", "mathematics", "biology"], weights=[0.25, 0.25, 0.25, 0.25])[0]

    # 2. Determine Class Chapter Constraints
    valid_chapter_ids: Optional[List[str]] = None
    valid_chapter_names: Optional[List[str]] = None

    if class_req in ["11", "12"]:
        class_int = int(class_req)
        chapters_res = (
            supabase.table("chapters")
            .select("id, name")
            .ilike("subject", chosen_subject)
            .eq("class_level", class_int)
            .execute()
        )
        valid_chapter_ids = [row["id"] for row in chapters_res.data]
        valid_chapter_names = [row["name"] for row in chapters_res.data if row.get("name")]

    # 3. Fetch User Practice Attempts (for 21-attempt repeat spacing logic - GATE 8.4)
    attempts_res = (
        supabase.table("practice_attempts")
        .select("id, question_id, is_correct, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=False)
        .execute()
    )

    all_user_attempts = attempts_res.data or []
    n_total_attempts = len(all_user_attempts)

    # Track most recent attempt index and status for each question
    latest_attempt_map: Dict[str, Dict[str, Any]] = {}
    for idx, att in enumerate(all_user_attempts):
        q_id = att.get("question_id")
        if q_id:
            latest_attempt_map[q_id] = {
                "is_correct": att.get("is_correct", False),
                "attempt_index": idx + 1 # 1-based attempt sequence
            }

    # 4. Fetch Candidate Questions for Chosen Subject
    query = (
        supabase.table("questions")
        .select("id, question_text, question_type, options, chapter_id, chapter_name, concept, difficulty, source, needs_manual, target_exams, discipline")
        .ilike("subject", chosen_subject)
        .is_("needs_manual", "null")
    )

    questions_res = query.execute()

    # 5. Filter Candidates by Exam, Class, Discipline, and Quality
    candidate_questions = []
    for q in questions_res.data:
        # Exclude mock test pool
        if q.get("source") == "extracted_master_content":
            continue

        # Exam Filter
        if not matches_exam(q.get("target_exams"), exam_mode):
            continue

        # Class Filter
        if valid_chapter_ids is not None:
            q_chap_id = q.get("chapter_id")
            q_chap_name = q.get("chapter_name")
            match_id = bool(q_chap_id and q_chap_id in valid_chapter_ids)
            match_name = False
            if valid_chapter_names and q_chap_name:
                match_name = any(
                    q_chap_name.strip().lower().replace("&", "and") == v_name.strip().lower().replace("&", "and")
                    for v_name in valid_chapter_names
                )
            if not (match_id or match_name):
                continue

        # Biology Discipline Filter (Botany / Zoology)
        if chosen_subject == "biology" and target_discipline:
            disc = str(q.get("discipline") or "").lower()
            if target_discipline not in disc:
                continue

        # Quality Filter (GATE 8.6)
        if not is_quality_question(q):
            continue

        candidate_questions.append(q)

    # 6. Empty Pool Handling (GATE 8.5)
    if not candidate_questions:
        return {
            "exhausted": True,
            "message": f"No eligible practice questions available for subject '{chosen_subject.capitalize()}' under selected exam/class filters."
        }

    # 7. Tier-Based Selection (GATE 8.4)
    # Tier 1: Previously wrong questions eligible after 21 attempts (Prioritized)
    # Tier 2: Unseen questions (Never attempted by user)
    # Tier 3: Correctly answered or locked questions (Re-enter on pool exhaustion)
    tier1_wrong_eligible = []
    tier2_unseen = []
    tier3_fallback = []

    for q in candidate_questions:
        q_id = q["id"]
        if q_id not in latest_attempt_map:
            tier2_unseen.append(q)
        else:
            att_info = latest_attempt_map[q_id]
            is_corr = att_info["is_correct"]
            att_idx = att_info["attempt_index"]
            attempts_since = n_total_attempts - att_idx

            if not is_corr and attempts_since >= 21:
                tier1_wrong_eligible.append(q)
            else:
                tier3_fallback.append(q)

    # Select single question based on priority hierarchy
    if tier1_wrong_eligible:
        selected = random.choice(tier1_wrong_eligible)
    elif tier2_unseen:
        selected = random.choice(tier2_unseen)
    else:
        selected = random.choice(tier3_fallback)

    q_type = selected.get("question_type")
    options = selected.get("options") if q_type != "numerical" else None

    # question.served — burns the item and starts the silent pace timer.
    # Never allowed to break serving.
    try:
        record_serve(user_id, selected["id"], context="practice")
    except Exception as e:
        print(f"[PRACTICE SERVE ERROR] Failed to record serve: {e}")

    return {
        "question_id": selected["id"],
        "question_text": selected.get("question_text"),
        "question_type": q_type,
        "options": options,
        "chapter_name": selected.get("chapter_name"),
        "concept": resolve_display_concept(selected["id"], selected.get("concept")),
        "difficulty": selected.get("difficulty")
    }


@router.post("/answer")
def submit_answer(
    req: PracticeAnswerRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Grades user answer and writes attempt row to practice_attempts.
    """
    # 1. Fetch target question with ground truth answers
    q_res = (
        supabase.table("questions")
        .select("id, question_type, correct_option, correct_value, value_tolerance, solution, options, difficulty")
        .eq("id", req.question_id)
        .limit(1)
        .execute()
    )

    if not q_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question with ID '{req.question_id}' not found."
        )

    q_data = q_res.data[0]
    q_type = q_data.get("question_type")

    is_correct = False
    correct_option = q_data.get("correct_option")
    correct_value = q_data.get("correct_value")
    solution = q_data.get("solution")

    # 2. Grade answer based on question_type
    if q_type == "numerical":
        if correct_value is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Numerical question lacks correct_value ground truth."
            )
        if req.chosen_value is not None:
            is_correct = grade_numerical(
                req.chosen_value, correct_value, q_data.get("value_tolerance")
            )
    else:
        if req.chosen_option and correct_option:
            is_correct = req.chosen_option.strip().lower() == correct_option.strip().lower()

    # 3. Score concept mastery BEFORE inserting the attempt row — the
    #    first-attempt gate counts prior attempts, so the current one must
    #    not be in the table yet. Scoring must never break grading.
    scoring = None
    try:
        scoring = apply_answer_scoring(
            user_id=user_id,
            question_id=req.question_id,
            is_correct=is_correct,
            raw_difficulty=q_data.get("difficulty"),
            mode="practice",
        )
    except Exception as e:
        print(f"[PRACTICE SCORING ERROR] Failed to score answer: {e}")

    # 4. Write attempt record to practice_attempts
    attempt_payload = {
        "user_id": user_id,
        "question_id": req.question_id,
        "is_correct": is_correct,
        "mode": "practice"
    }

    try:
        supabase.table("practice_attempts").insert(attempt_payload).execute()
    except Exception as e:
        print(f"[PRACTICE ANSWER ERROR] Failed to record attempt: {e}")

    return {
        "is_correct": is_correct,
        "correct_option": correct_option,
        "correct_value": correct_value,
        "solution": solution,
        "scoring": scoring
    }


@router.get("/stats")
def get_practice_stats(
    user_id: str = Depends(get_current_user_id)
):
    """
    Calculates lifetime practice statistics for the authenticated user.
    """
    attempts_res = (
        supabase.table("practice_attempts")
        .select("id, is_correct")
        .eq("user_id", user_id)
        .execute()
    )

    attempts = attempts_res.data or []
    attempted_count = len(attempts)
    correct_count = sum(1 for a in attempts if a.get("is_correct"))

    accuracy = round((correct_count / attempted_count) * 100, 1) if attempted_count > 0 else 0.0

    return {
        "attempted": attempted_count,
        "correct": correct_count,
        "accuracy": accuracy
    }


@router.post("/explain")
def explain_drona(
    req: PracticeExplainRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Creates a practice_explain Drona session seeded with this question's full
    context (stem, options, the student's answer, the correct answer, the
    solution). The live tutor turn itself is generated over the WebSocket
    (POST /drona/session/{id}/live), not here — this endpoint only creates
    the session row and returns the session_id the frontend needs to open it.
    """
    q_res = (
        supabase.table("questions")
        .select("id, question_text, question_type, options, correct_option, correct_value, value_tolerance, solution, chapter_id")
        .eq("id", req.question_id)
        .limit(1)
        .execute()
    )
    if not q_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question with ID '{req.question_id}' not found."
        )

    q = q_res.data[0]
    q_type = q.get("question_type")
    correct_option = q.get("correct_option")
    correct_value = q.get("correct_value")

    # Re-derive correctness with the same rule /practice/answer grades with,
    # rather than trusting the client — also makes this endpoint work even if
    # /practice/answer was never called for this question_id.
    is_correct = False
    if q_type == "numerical" and correct_value is not None and req.chosen_value is not None:
        is_correct = grade_numerical(req.chosen_value, correct_value, q.get("value_tolerance"))
    elif req.chosen_option and correct_option:
        is_correct = req.chosen_option.strip().lower() == correct_option.strip().lower()

    language = normalize_language(req.language)
    voice = normalize_voice(req.voice)

    practice_seed = {
        "question_text": q.get("question_text"),
        "question_type": q_type,
        "options": q.get("options"),
        "chosen_option": req.chosen_option,
        "chosen_value": req.chosen_value,
        "correct_option": correct_option,
        "correct_value": correct_value,
        "solution": q.get("solution"),
        "is_correct": is_correct,
    }

    session_row = {
        "user_id": user_id,
        "mode": "practice_explain",
        "question_id": req.question_id,
        "chapter_id": q.get("chapter_id"),
        "practice_seed": practice_seed,
        "language": language,
        "tutor_voice": voice,
        "phase": "teaching",  # WS auto-fires turn 1 on connect when phase == "teaching"
        "prompt_version": "practice_explain_v1",
    }

    sess_res = supabase.table("drona_sessions").insert([session_row]).execute()
    if not sess_res.data:
        raise HTTPException(status_code=500, detail="Failed to create practice-explain session")

    session_id = sess_res.data[0]["id"]
    return {
        "session_id": session_id,
        "phase": "teaching",
        "language": language,
        "tutor_voice": voice,
        "tutor_name": tutor_name(voice),
    }
