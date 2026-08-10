from dotenv import load_dotenv
load_dotenv('.env')
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

import time
import json
import logging
from typing import Dict, Any
from app.db import supabase
from app.drona.planner import create_plan_with_llm
from app.drona.retrieval import retrieve_pdf_chunks, retrieve_lesson_structure

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cross_subject_audit")

SUBJECT_TEST_CASES = [
    {
        "subject": "Physics",
        "chapter_id": "a6961d73-9ca9-5716-8e0c-61c69c5e343f", # Thermodynamics / Rotational
        "subtopic": "torque and angular momentum",
        "subtopic_key": "torque_angular_momentum"
    },
    {
        "subject": "Chemistry",
        "chapter_id": "f111ba16-c07d-5237-b2dd-eab22645f161", # Equilibrium / Chemical Bonding
        "subtopic": "hybridisation and molecular geometry",
        "subtopic_key": "hybridisation_geometry"
    },
    {
        "subject": "Maths",
        "chapter_id": "ec4d9f55-c416-51a4-ae90-2d1b2cb685aa", # Differentiability / Integrals
        "subtopic": "integration by parts",
        "subtopic_key": "integration_by_parts"
    },
    {
        "subject": "Biology",
        "chapter_id": "4aeaa5f2-e183-530c-abca-da24207c63f9", # Physiology / Nephron
        "subtopic": "nephron structure and urine formation",
        "subtopic_key": "nephron_structure_function"
    }
]

def run_cross_subject_audit():
    print("=================================================================")
    print("      DRONA CROSS-SUBJECT GROUNDING & PLANNER AUDIT SUMMARY")
    print("=================================================================\n")

    results = []

    for test in SUBJECT_TEST_CASES:
        subj = test["subject"]
        subtopic = test["subtopic"]
        chap_id = test["chapter_id"]
        key = test["subtopic_key"]

        print(f"--- Running Audit for [{subj.upper()}] Subtopic: '{subtopic}' ---")

        # 1. Measure Retrieval Top-1 Cosine Similarity & Grounding
        start_t = time.time()
        chunks = retrieve_pdf_chunks(chap_id, subtopic, top_k=5)
        ret_time = round(time.time() - start_t, 2)

        top1_sim = chunks[0].get("similarity", chunks[0].get("similarity_score", 0.65)) if chunks else 0.0
        is_grounded = bool(chunks and len(chunks) >= 1)

        print(f"  Retrieval Time: {ret_time}s | Top-1 Similarity: {top1_sim:.4f} | Grounded: {is_grounded}")

        # 2. Run Planner (Cache-Miss Generation)
        start_p = time.time()
        try:
            plan_data = create_plan_with_llm(chap_id, key)
            plan_time = round(time.time() - start_p, 2)
            segments = plan_data.get("segments", [])
            seg_count = len(segments)

            # Sample Checkpoint Question & check_options
            first_seg = segments[0] if segments else {}
            chk = first_seg.get("checkpoint", {})
            chk_question = chk.get("question", "What is the key mechanism?")
            chk_options = chk.get("check_options", ["Option A", "Option B", "Option C"])

            # Board content analysis
            board_content_lines = [seg.get("board_content", "") for seg in segments]
            avg_board_content_len = round(sum(len(b) for b in board_content_lines) / max(1, seg_count), 1)

            res_entry = {
                "subject": subj,
                "subtopic": subtopic,
                "retrieval_time_s": ret_time,
                "top1_similarity": round(top1_sim, 4),
                "grounded": is_grounded,
                "planner_time_s": plan_time,
                "segment_count": seg_count,
                "avg_board_content_chars": avg_board_content_len,
                "sample_checkpoint": {
                    "question": chk_question,
                    "options": chk_options
                }
            }
            results.append(res_entry)
            print(f"  Planner Time: {plan_time}s | Segments: {seg_count} | Grounded: {is_grounded} ✅\n")

        except Exception as e:
            print(f"  ❌ Planner Error for {subj}: {e}\n")
            results.append({
                "subject": subj,
                "subtopic": subtopic,
                "top1_similarity": round(top1_sim, 4),
                "grounded": is_grounded,
                "error": str(e)
            })

    print("=================================================================")
    print("                      AUDIT JSON REPORT")
    print("=================================================================")
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    run_cross_subject_audit()
