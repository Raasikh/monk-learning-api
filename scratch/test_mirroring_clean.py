import asyncio
import json
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.drona.models import get_drona_client, get_model_name
from app.drona.prompt_loader import load_prompt
from app.drona.tutor import strip_fences
from app.drona.voice_proxy import split_into_sentences

async def run_mirror_test():
    tutor_prompt = load_prompt("tutor.md")
    client = get_drona_client()
    model_name = get_model_name("tutor")

    user_msg = """[CURRENT SEGMENT]
{
  "objective": "Speed and Velocity",
  "teaching_notes": "Define speed, formula speed = distance / time, and dimensional formula [L T^-1]."
}

[SESSION STATE]
{
  "language": "hinglish",
  "phase": "teaching",
  "current_segment": 1,
  "total_segments": 6
}

[STUDENT UTTERANCE]
"Teach me Speed. Explain what speed is, its formula, and its dimensional formula."
"""

    messages = [
        {"role": "system", "content": tutor_prompt},
        {"role": "user", "content": user_msg}
    ]

    res = client.chat.completions.create(
        model=model_name,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=1800
    )

    raw_text = res.choices[0].message.content or "{}"
    data = json.loads(strip_fences(raw_text))

    speech = data.get("speech", "")
    events = data.get("board_events", [])

    sentences = split_into_sentences(speech)
    print(f"RAW SPEECH (len={len(speech)}, sentences={len(sentences)}):\n{speech}\n")
    print(f"RAW BOARD EVENTS (len={len(events)}):\n{json.dumps(events, indent=2)}\n")

    print("\n| Sentence # | Spoken Sentence Text | Matching Board Event (`seq`, `type`, Content) |")
    print("|---|---|---|")
    for i, s in enumerate(sentences, 1):
        matching = next((e for e in events if e.get("seq") == i), None)
        if not matching and i <= len(events):
            matching = events[i-1]
        
        if matching:
            t = matching.get("type", "")
            if t == "formula":
                c = f"**Formula** (`seq={matching.get('seq')}`): `${matching.get('latex', '')}$`"
            else:
                c = f"**{t.capitalize()}** (`seq={matching.get('seq')}`): \"{matching.get('text', '')}\""
        else:
            c = "*(No Board Event — Conversational/Filler)*"
        print(f"| **{i}** | \"{s}\" | {c} |")

if __name__ == "__main__":
    asyncio.run(run_mirror_test())
