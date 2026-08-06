import os
import time
import json
import asyncio
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.drona.models import get_drona_client, get_model_name
from app.drona.prompt_loader import load_prompt

def benchmark_tutor_turn():
    t0 = time.time()
    client = get_drona_client()
    tutor_prompt = load_prompt("tutor")

    messages = [
        {"role": "system", "content": tutor_prompt},
        {"role": "user", "content": """[CURRENT SEGMENT]
{"id": 1, "title": "Thermodynamic Systems", "objective": "Define open, closed, isolated systems", "board_content": "$$ \\Delta U = Q - W $$", "checkpoint": {"question": "Is a sealed pressure cooker an open or closed system?", "model_answer": "Closed system", "rubric": "Correct if states closed because heat transfers but mass does not."}}

[SESSION STATE]
{"phase": "teaching", "current_segment": 1}

[STUDENT UTTERANCE]
"Begin lesson segment"
"""}
    ]

    print("=== BENCHMARKING DEEPSEEK FLASH TUTOR TURN LATENCY ===")
    res = client.chat.completions.create(
        model=get_model_name("tutor"),
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=1500
    )
    t_end = time.time()

    content = res.choices[0].message.content or "{}"
    print("Raw Content:", repr(content[:200]))
    from app.drona.tutor import strip_fences
    parsed = json.loads(strip_fences(content))
    speech = parsed.get("speech", "")
    words = len(speech.split())

    tokens = res.usage.completion_tokens if hasattr(res, "usage") else 0

    print(f"1. Total Turn Generation Duration: {round(t_end - t0, 2)} seconds")
    print(f"2. Output Tokens Generated: {tokens}")
    print(f"3. Spoken Speech Word Count: {words} words (Constraint: 60-120 words)")
    print(f"4. Spoken Speech Preview: \"{speech[:100]}...\"")

if __name__ == "__main__":
    benchmark_tutor_turn()
