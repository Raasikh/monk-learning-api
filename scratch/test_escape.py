import re
import json

def repair_json_escapes(text: str) -> str:
    """
    Repairs LaTeX backslashes inside JSON string literals.
    LaTeX backslashes before commands like \text, \frac, \vec, \begin, \end, \alpha, \beta, \theta, \delta, \times, \cdot, \bullet MUST be double-escaped.
    """
    # 1. First, repair known LaTeX command backslashes (including those starting with \t or \f like \text, \frac, \theta, \times)
    latex_cmds = r'\\(text|frac|vec|begin|end|alpha|beta|theta|delta|gamma|sigma|lambda|pi|mu|rho|tau|phi|psi|omega|Delta|Gamma|Theta|Lambda|Pi|Sigma|Omega|times|cdot|bullet|sqrt|approx|equiv|leq|geq|neq|pm|infty|partial|nabla|int|sum|prod|lim|log|ln|sin|cos|tan|cot|sec|csc|sinh|cosh|tanh|hat|bar|tilde|overline|underline|overbrace|underbrace|left|right|quad|qquad|bold|mathbf|mathrm|mathit|mathsf|mathcal)\b'
    text = re.sub(latex_cmds, r'\\\\\1', text)

    # 2. Then repair any remaining single backslashes not followed by valid JSON escape sequence or quotes
    pattern = re.compile(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})')
    text = pattern.sub(lambda m: '\\\\' + m.group(0)[1:], text)
    return text

raw_llm_output = '''{
    "segments": [
        {
            "objective": "Understand vectors",
            "teaching_notes": "Use \\vec{A} + \\vec{B}",
            "board_content": "\\text{Vector Resolution} \\frac{\\vec{A}}{\\vec{B}} \\bullet \\theta \\alpha \\Delta"
        }
    ]
}'''

print("=== RAW LLM OUTPUT ===")
print(raw_llm_output)

try:
    json.loads(raw_llm_output)
    print("RAW JSON.LOADS: SUCCESS")
except Exception as e:
    print(f"RAW JSON.LOADS FAILED: {e}")

repaired = repair_json_escapes(raw_llm_output)
print("\n=== REPAIRED OUTPUT ===")
print(repaired)

try:
    data = json.loads(repaired)
    print("\nREPAIRED JSON.LOADS: SUCCESS!")
    print("Parsed board_content:", data["segments"][0]["board_content"])
except Exception as e:
    print(f"REPAIRED JSON.LOADS FAILED: {e}")
