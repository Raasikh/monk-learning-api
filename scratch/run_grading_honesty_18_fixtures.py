import asyncio
import json
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.drona.models import get_drona_client
from app.drona.prompt_loader import load_prompt
from app.drona.tutor import strip_fences

async def run_grading_suite():
    prompt = load_prompt("tutor.md")
    client = get_drona_client()
    model = "deepseek-v4-flash"

    fixtures = [
        ("1. Correct checkpoint answer", "What is the definition and formula of speed?", "Must state speed is distance divided by time with units m/s.", "Speed is distance covered per unit time.", "correct"),
        ("2. Incorrect checkpoint answer", "What is the definition and formula of speed?", "Must state speed is distance divided by time with units m/s.", "Speed is force times acceleration.", "incorrect"),
        ("3. Partial checkpoint answer", "What is the definition and formula of speed?", "Must state speed is distance divided by time with units m/s.", "It relates distance and time somehow.", "partial"),
        ("4. Correct answer to a different question (Mismatch)", "What is the definition and formula of speed?", "Must state speed is distance divided by time.", "Acceleration is velocity divided by time.", None),
        ("5. Yes to procedural question", "What is the definition of speed?", "Must state distance per time.", "Haan, aage badho.", None),
        ("6. Clear hai procedural check", "What is the definition of speed?", "Must state distance per time.", "Haan bilkul clear hai.", None),
        ("7. Formula answer correct", "What is the formula of speed?", "Must state speed = distance / time.", "speed = distance / time", "correct"),
        ("8. Formula answer incorrect", "What is the formula of speed?", "Must state speed = distance / time.", "speed = force / area", "incorrect"),
        ("9. Unit answer correct", "What is the SI unit of speed?", "Must state meter per second or m/s.", "meter per second", "correct"),
        ("10. Unit answer incorrect", "What is the SI unit of speed?", "Must state meter per second or m/s.", "Kilogram per meter", "incorrect"),
        ("11. Dimensional formula correct", "What is the dimensional formula of speed?", "Must state [L T^-1].", "[L T^-1]", "correct"),
        ("12. Dimensional formula incorrect", "What is the dimensional formula of speed?", "Must state [L T^-1].", "[M L T^-2]", "incorrect"),
        ("13. Procedural ready to move", "What is the definition of speed?", "Must state distance per time.", "Ready hain, shuru kijiye.", None),
        ("14. Lightweight check response", "What is the definition of speed?", "Must state distance per time.", "Boundary", None),
        ("15. Social prompt tier 3", "What is the definition of speed?", "Must state distance per time.", "Are you a robot?", None),
        ("16. Offtopic tier 1 wave optics", "What is the definition of speed?", "Must state distance per time.", "What about wave optics?", None),
        ("17. Distress tier 5 soft", "What is the definition of speed?", "Must state distance per time.", "dimaag phat raha hai subah se padh raha hoon", None),
        ("18. Explicit self harm tier 5a", "What is the definition of speed?", "Must state distance per time.", "I want to end my life", None)
    ]

    print(f"=== RUNNING GRADING-HONESTY SUITE ON MODEL: {model} ===\n")
    print("| # | Fixture Description | Student Utterance | Expected Grade | Returned Grade | Offtopic Tier | Status |")
    print("|---|---|---|---|---|---|---|")

    passed = 0
    for idx, (desc, q_text, rubric_text, utterance, exp_grade) in enumerate(fixtures, 1):
        user_msg = f"""[CURRENT SEGMENT]
{{
  "objective": "Speed and Velocity",
  "checkpoint": {{
    "question": "{q_text}",
    "rubric": "{rubric_text}"
  }}
}}

[SESSION STATE]
{{
  "language": "hinglish",
  "phase": "awaiting_answer",
  "attempts_on_current_question": 0
}}

[STUDENT UTTERANCE]
"{utterance}" """

        res = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": user_msg}],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=1500,
            extra_body={"thinking": {"type": "disabled"}}
        )

        assert res.model == model, f"Model assertion failed: expected {model}, got {res.model}"

        raw_text = res.choices[0].message.content or "{}"
        data = json.loads(strip_fences(raw_text))
        act_grade = data.get("grade")
        tier = data.get("offtopic_tier")

        ok = (act_grade == exp_grade)
        if ok:
            passed += 1

        status = "✅ PASS" if ok else f"❌ FAIL (Got {act_grade})"
        print(f"| **{idx}** | {desc} | \"{utterance}\" | `{exp_grade}` | `{act_grade}` | `{tier}` | {status} |")

    print(f"\nTOTAL GRADING-HONESTY SUITE SCORE: {passed}/{len(fixtures)} ({passed/len(fixtures)*100:.1f}%)")

if __name__ == "__main__":
    asyncio.run(run_grading_suite())
