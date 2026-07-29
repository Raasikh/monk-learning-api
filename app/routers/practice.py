import random
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import get_current_user_id
from app.db import supabase

router = APIRouter(prefix="/practice", tags=["practice"])


# --- Request & Response Models ---

class PracticeNextRequest(BaseModel):
    subject: str
    chapter_id: Optional[str] = None
    class_level: Optional[str] = None


class PracticeAnswerRequest(BaseModel):
    question_id: str
    chosen_option: Optional[str] = None
    chosen_value: Optional[float] = None


class PracticeExplainRequest(BaseModel):
    question_id: str
    chosen_option: Optional[str] = None
    chosen_value: Optional[float] = None


# --- Endpoints ---

@router.post("/next")
def get_next_question(
    req: PracticeNextRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Selects 1 unseen practice question from non-mock, non-quarantined pool.
    Answer fields (correct_option, correct_value, solution, etc.) are strictly omitted.
    """
    # 1. Determine target class_level if not explicitly supplied
    effective_class = req.class_level
    if not effective_class:
        profile_res = (
            supabase.table("profiles")
            .select("enrolled_class")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if profile_res.data and profile_res.data[0].get("enrolled_class"):
            effective_class = profile_res.data[0]["enrolled_class"]

    # 2. Determine valid chapter IDs based on filters
    valid_chapter_ids: Optional[List[str]] = None
    if req.chapter_id:
        valid_chapter_ids = [req.chapter_id]
    elif effective_class:
        chapters_res = (
            supabase.table("chapters")
            .select("id")
            .eq("subject", req.subject)
            .eq("class_level", effective_class)
            .execute()
        )
        valid_chapter_ids = [row["id"] for row in chapters_res.data]

    # 3. Fetch list of seen question IDs for this user
    attempts_res = (
        supabase.table("practice_attempts")
        .select("question_id")
        .eq("user_id", user_id)
        .execute()
    )
    seen_ids = set(
        row["question_id"]
        for row in attempts_res.data
        if row.get("question_id")
    )

    # 4. Fetch candidate questions with EXPLICIT non-answer columns
    # Core Security Rule: never select correct_option, correct_value, solution, etc.
    query = (
        supabase.table("questions")
        .select("id, question_text, question_type, options, chapter_id, chapter_name, concept, difficulty, source, needs_manual")
        .eq("subject", req.subject)
        .is_("needs_manual", "null")
    )

    # Execute candidate query
    questions_res = query.execute()

    # 5. Filter in-memory for non-mock pool, class/chapter constraints, and unseen exclusion
    candidates = []
    for q in questions_res.data:
        # Pool Rule: source IS DISTINCT FROM 'extracted_master_content'
        if q.get("source") == "extracted_master_content":
            continue
        
        # Exclude seen questions
        if q["id"] in seen_ids:
            continue

        # Class/Chapter filtering constraint:
        # Questions with a null chapter_id are only served when no class/chapter filter is applied.
        q_chap_id = q.get("chapter_id")
        if valid_chapter_ids is not None:
            if not q_chap_id or q_chap_id not in valid_chapter_ids:
                continue

        candidates.append(q)

    # 6. Check if unseen pool is exhausted
    if not candidates:
        return {
            "exhausted": True,
            "message": f"No unseen questions available for subject '{req.subject}' under current filters."
        }

    # 7. Randomly select 1 question
    selected = random.choice(candidates)

    q_type = selected.get("question_type")
    options = selected.get("options") if q_type != "numerical" else None

    return {
        "question_id": selected["id"],
        "question_text": selected.get("question_text"),
        "question_type": q_type,
        "options": options,
        "chapter_name": selected.get("chapter_name"),
        "concept": selected.get("concept"),
        "difficulty": selected.get("difficulty")
    }


@router.post("/answer")
def submit_answer(
    req: PracticeAnswerRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Grades a practice question submission and records the attempt.
    """
    # 1. Fetch target question using secret key (RLS bypassed)
    q_res = (
        supabase.table("questions")
        .select("id, question_type, correct_option, correct_value, value_tolerance, solution")
        .eq("id", req.question_id)
        .limit(1)
        .execute()
    )

    if not q_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question with ID '{req.question_id}' not found"
        )

    question = q_res.data[0]
    q_type = question.get("question_type")
    is_correct = False

    # 2. Grade submission
    if q_type == "numerical":
        correct_val = question.get("correct_value")
        if correct_val is None:
            # Ungradeable numerical question -> HTTP 409, do NOT write attempt
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ungradeable numerical question: correct_value is missing"
            )

        if req.chosen_value is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="chosen_value is required for numerical questions"
            )

        tolerance = float(question.get("value_tolerance") or 0.0)
        is_correct = abs(float(req.chosen_value) - float(correct_val)) <= tolerance

    else:
        # MCQ (single_correct, multiple_correct, mcq, etc.)
        if not req.chosen_option:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="chosen_option is required for MCQ questions"
            )

        correct_opt = str(question.get("correct_option") or "").strip().lower()
        chosen_opt = str(req.chosen_option).strip().lower()
        is_correct = (chosen_opt == correct_opt)

    # 3. Write practice_attempts row
    attempt_data = {
        "user_id": user_id,
        "question_id": req.question_id,
        "chosen_option": req.chosen_option,
        "chosen_value": req.chosen_value,
        "is_correct": is_correct,
        "mode": "practice"
    }

    supabase.table("practice_attempts").insert(attempt_data).execute()

    # 4. Return answer & explanation payload
    return {
        "is_correct": is_correct,
        "correct_option": question.get("correct_option"),
        "correct_value": question.get("correct_value"),
        "solution": question.get("solution")
    }


@router.get("/stats")
def get_practice_stats(
    user_id: str = Depends(get_current_user_id)
):
    """
    Returns lifetime practice stats for the user using database count queries.
    """
    # 1. Total attempted count (head=True, count="exact")
    total_res = (
        supabase.table("practice_attempts")
        .select("id", count="exact", head=True)
        .eq("user_id", user_id)
        .eq("mode", "practice")
        .execute()
    )
    attempted = total_res.count or 0

    # 2. Total correct count
    correct_res = (
        supabase.table("practice_attempts")
        .select("id", count="exact", head=True)
        .eq("user_id", user_id)
        .eq("mode", "practice")
        .eq("is_correct", True)
        .execute()
    )
    correct = correct_res.count or 0

    accuracy = round(correct / attempted, 4) if attempted > 0 else 0.0

    # 3. Breakdown by subject
    # Fetch distinct subjects from questions for attempted practice questions
    attempts_res = (
        supabase.table("practice_attempts")
        .select("question_id, is_correct")
        .eq("user_id", user_id)
        .eq("mode", "practice")
        .execute()
    )

    by_subject_dict: Dict[str, Dict[str, int]] = {}
    if attempts_res.data:
        question_ids = list(set(row["question_id"] for row in attempts_res.data if row.get("question_id")))
        
        # Batch fetch subjects for these question_ids
        q_res = (
            supabase.table("questions")
            .select("id, subject")
            .in_("id", question_ids)
            .execute()
        )
        q_subject_map = {q["id"]: q.get("subject", "Unknown") for q in q_res.data}

        for row in attempts_res.data:
            q_id = row.get("question_id")
            subj = q_subject_map.get(q_id, "Unknown")
            if subj not in by_subject_dict:
                by_subject_dict[subj] = {"attempted": 0, "correct": 0}
            
            by_subject_dict[subj]["attempted"] += 1
            if row.get("is_correct"):
                by_subject_dict[subj]["correct"] += 1

    by_subject_list = []
    for subj, s_data in by_subject_dict.items():
        s_att = s_data["attempted"]
        s_corr = s_data["correct"]
        s_acc = round(s_corr / s_att, 4) if s_att > 0 else 0.0
        by_subject_list.append({
            "subject": subj,
            "attempted": s_att,
            "correct": s_corr,
            "accuracy": s_acc
        })

    return {
        "attempted": attempted,
        "correct": correct,
        "accuracy": accuracy,
        "by_subject": by_subject_list
    }


@router.post("/explain")
def explain_question(
    req: PracticeExplainRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Stub for Drona explanation route. Validates question existence and returns 501.
    """
    q_res = (
        supabase.table("questions")
        .select("id")
        .eq("id", req.question_id)
        .limit(1)
        .execute()
    )

    if not q_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question with ID '{req.question_id}' not found"
        )

    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "status": "not_implemented",
            "message": "Drona explanations coming soon"
        }
    )
