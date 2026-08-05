import re
import json

def repair_json_escapes(text: str) -> str:
    """
    Robust JSON LaTeX escape repair:
    Doubles any backslash in JSON string values that is NOT already double-escaped (\\\\) or an escaped quote (\\\").
    This fixes \\Delta, \\text, \\frac, \\neq, \\vec, etc.
    """
    if not text:
        return ""
    # Matches a single backslash that is not preceded by a backslash and not followed by a quote or backslash
    pattern = re.compile(r'(?<!\\)\\(?!["\\])')
    return pattern.sub(r'\\\\', text)

raw_llm_json = '''{
    "topic": "Chemical Thermodynamics",
    "board_content": "$$\\Delta U = q + w$$\\n$$q > 0 \\text{ if heat absorbed}$$\\n$$\\Delta U = 0$$\\n$$q \\neq 0$$\\n$$\\vec{A} \\bullet \\theta$$\\n$$\\frac{1}{2}$$"
}'''

print("RAW INPUT:\n", raw_llm_json)

try:
    json.loads(raw_llm_json)
    print("RAW LOAD: SUCCESS")
except Exception as e:
    print("RAW LOAD FAILED:", e)

repaired = repair_json_escapes(raw_llm_json)
print("\nREPAIRED INPUT:\n", repaired)

try:
    parsed = json.loads(repaired)
    print("\nREPAIRED LOAD: SUCCESS!")
    print("PARSED BOARD:\n", parsed["board_content"])
except Exception as e:
    print("REPAIRED LOAD FAILED:", e)
