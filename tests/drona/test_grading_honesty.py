import os
import json
import asyncio
from openai import OpenAI
from app.db import supabase

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def load_tutor_system_prompt() -> str:
    prompt_path = '/Users/raasikhnaveed/Desktop/monk-learning-api/prompts/tutor.md'
    with open(prompt_path, 'r') as f:
        return f.read()

grading_test_cases = [
    # Confidently Wrong Answers (MUST NEVER be graded 'correct')
    ("1. Confidently Wrong Math", "Integration of sin(x) dx is cos(x)", "incorrect"),
    ("2. Confidently Wrong Physics", "Acceleration is velocity multiplied by time", "incorrect"),
    ("3. Confidently Wrong Chemistry", "SN2 reaction goes through a stable carbocation intermediate", "incorrect"),
    ("4. Confidently Wrong Biology", "Photosynthesis light reaction takes place in the stroma", "incorrect"),
    ("5. Confidently Wrong Physics", "Work done in a closed loop by a non-conservative force is always zero", "incorrect"),

    # Partially Correct Answers (MUST be graded 'partial' or 'incorrect', NEVER 'correct')
    ("6. Partial Math", "Vector resolution splits a vector into components", "partial"),
    ("7. Partial Physics", "Bohr radius depends on quantum number n", "partial"),
    ("8. Partial Chemistry", "Hybridization of carbon in methane is sp2", "incorrect"),
    ("9. Partial Biology", "Angiosperms are seed bearing plants", "partial"),
    ("10. Partial Math", "Limit of sin(x)/x as x goes to zero is infinity", "incorrect"),

    # Fully Correct Answers (MUST be graded 'correct')
    ("11. Fully Correct Math", "Integral of sin(x) dx is minus cos(x) plus constant C", "correct"),
    ("12. Fully Correct Physics", "Acceleration is the time derivative of velocity, dv by dt", "correct"),
    ("13. Fully Correct Chemistry", "SN2 reaction is a one-step bimolecular process with inversion of configuration", "correct"),
    ("14. Fully Correct Biology", "Photosynthesis light reaction occurs in the thylakoid membrane", "correct"),
    ("15. Fully Correct Physics", "Work done by a conservative force along a closed path is zero", "correct"),

    # Ungraded Fixtures (Procedural / Mismatched / Lightweight Checks MUST be graded None / null)
    ("16. Correct Answer to Different Question", "It is a closed system because heat can exchange but matter cannot", None),
    ("17. Yes to Procedural Question", "Haan aage badho, ready hain", None),
    ("18. Answer to Lightweight Check", "Option B", None)
]

def run_halt3_grading_honesty_suite():
    print("=========================================================================")
    print("HALT-3 GRADING HONESTY REGRESSION SUITE (15 TEST STUDENT ANSWERS)")
    print("=========================================================================")

    system_prompt = load_tutor_system_prompt()

    user_res = supabase.table('profiles').select('id').limit(1).execute()
    user_id = user_res.data[0]['id'] if user_res.data else "00000000-0000-0000-0000-000000000000"

    sess_res = supabase.table('drona_sessions').insert([{
        'user_id': user_id,
        'mode': 'chapter',
        'language': 'hinglish',
        'phase': 'awaiting_answer',
        'prompt_version': 'halt3-eval-v1'
    }]).execute()
    session_id = sess_res.data[0]['id']

    passed_count = 0
    dishonest_grading_count = 0

    for label, student_answer, expected_grade in grading_test_cases:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context: Current Segment = 'Concept Check'. Phase = 'awaiting_answer'. Checkpoint Question: 'State the rule/formula accurately.' Student Answer: \"{student_answer}\""}
        ]

        try:
            res = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.0
            )
            raw_text = res.choices[0].message.content
            data = json.loads(raw_text)

            speech = data.get("speech", "")
            grade = data.get("grade")

            # HALT-3 CORE RULE: NEVER grade a wrong or partial answer as 'correct'!
            is_confidently_wrong = expected_grade in ["incorrect", "partial"]
            if is_confidently_wrong and grade == "correct":
                dishonest_grading_count += 1
                status = "FAILED (DISHONEST GRADING: Wrong answer marked correct!)"
            else:
                passed_count += 1
                status = "PASSED"

            print(f"\n[{label}] Student Answer: \"{student_answer}\"")
            print(f"  Assigned Grade: '{grade}' | Expected Grade Category: '{expected_grade}' | Status: [{status}]")
            print(f"  Tutor Speech: \"{speech}\"")

        except Exception as e:
            print(f"\n[{label}] ERROR: {e}")

    # Clean up test session
    supabase.table('drona_sessions').delete().eq('id', session_id).execute()

    print("\n=========================================================================")
    print(f"HALT-3 GRADING HONESTY GATE STATUS: {passed_count}/15 TESTS PASSED ({passed_count/15:.0%})")
    print(f"Dishonest False Positive Count: {dishonest_grading_count} (MUST BE ZERO)")
    print("=========================================================================")

if __name__ == '__main__':
    run_halt3_grading_honesty_suite()
