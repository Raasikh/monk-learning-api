"""Run a real teaching turn per subject and check the diagram survives to SVG.

    python3 scripts/probe_diagrams.py            # all four subjects
    DIAGRAM_OUT=/tmp/svg python3 scripts/probe_diagrams.py

Costs real DeepSeek calls, so it is not in the pytest suite.

Not a unit test of the templates — those pass already. This checks the whole
path a student actually gets: the model is asked to teach a diagram-worthy
concept, it must choose a template and fill its params, and the result must
materialise into SVG that honours the board contract in diagram_templates.py.
Every stage between "cue fires" and "picture appears" can drop it silently.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.drona.diagram_templates import TEMPLATES, render
from app.drona.models import get_drona_client, get_model_name
from app.drona.prompt_loader import load_prompt
from app.drona.tutor import suggest_diagram_template

CASES = [
    ("physics", "Rotational Motion", "Equilibrium of Rigid Bodies",
     "A ladder leans against a smooth wall. Show the forces keeping it in equilibrium."),
    ("chemistry", "Chemical Bonding", "Ionic Bond Formation, Lattice Enthalpy and Born-Haber Cycle",
     "Walk through the Born-Haber cycle for NaCl step by step."),
    ("mathematics", "Limits and Derivatives", "Derivative as Slope of a Tangent and Rate of Change",
     "Derive the derivative as the limit of the slope of a secant."),
    ("biology", "Cell Cycle and Cell Division", "Mitosis vs Meiosis: Comparison of Events and Products",
     "Compare mitosis and meiosis across their key events and products."),
]

# From the module docstring: what the web board can actually draw and restyle.
DRAWABLE = {"path", "line", "polyline", "polygon", "circle", "ellipse", "rect"}
BANNED = ("<script", "onload=", "onclick=", "<image", "<foreignobject", "xlink:href")


def diagram_directive(hint: str) -> str:
    """The per-turn directive, read out of tutor.py rather than copied.

    Production does NOT rely on the prompt's general diagram rule. A directive
    naming THE template for THIS turn is what took emission from 2/4 to 4/4,
    and without it this probe measures a code path no student ever hits — the
    first run of this script returned 0/4 for exactly that reason and nearly
    got reported as a product failure.

    It is extracted from the source so the probe cannot drift from production
    when someone edits the wording. If this raises, the directive has moved or
    been removed, which is itself the thing worth knowing.
    """
    src = Path(__file__).resolve().parents[1] / "app" / "drona" / "tutor.py"
    text = src.read_text()
    start = text.index('diagram_directive = (')
    end = text.index('\n        )', start)
    literal = text[text.index('f"', start):end]
    parts = re.findall(r'f"((?:[^"\\]|\\.)*)"', literal)
    if not parts:
        raise RuntimeError("could not extract the diagram directive from tutor.py")
    body = "".join(parts).replace("\\n", "\n").replace('\\"', '"')
    return body.replace("{_diag_hint}", hint)


def turn(concept: str, chapter: str, subject: str, notes: str, hint: str = ""):
    state = f"""[SESSION STATE]
student_name: Arjun
language: english
phase: teaching
current_segment: 3 of 8

[CURRENT SEGMENT]
subject: {subject}
chapter: {chapter}
title: {concept}
objective: {concept}
teaching_notes: {notes}

[STUDENT UTTERANCE]
"continue"
""" + (diagram_directive(hint) if hint else "")
    res = get_drona_client().chat.completions.create(
        model=get_model_name("tutor"),
        messages=[{"role": "system", "content": load_prompt("tutor")},
                  {"role": "user", "content": state}],
        response_format={"type": "json_object"}, temperature=0.0,
        max_tokens=3000, timeout=120,
        extra_body={"thinking": {"type": "disabled"}},
    )
    return json.loads(res.choices[0].message.content or "{}")


def main() -> int:
    bad = 0
    for subject, chapter, concept, notes in CASES:
        cue = suggest_diagram_template(concept, notes, "")
        print(f"\n{'=' * 78}\n{subject.upper()}  ·  {chapter}\n  concept: {concept}\n  cue fired: {cue}")
        reply = turn(concept, chapter, subject, notes, cue or "")
        events = [e for e in (reply.get("board_events") or []) if isinstance(e, dict)]
        diag = next((e for e in events if e.get("type") == "diagram"), None)
        print(f"  board events: {len(events)}   diagram emitted: {bool(diag)}")
        if not diag:
            print(f"  ** NO DIAGRAM ** kinds={[e.get('type') for e in events]}")
            bad += 1
            continue

        name, params = diag.get("template"), diag.get("params")
        print(f"  template: {name}   params: {list(params) if isinstance(params, dict) else params}")
        if name not in TEMPLATES:
            print(f"  ** UNKNOWN TEMPLATE **"); bad += 1; continue
        if not isinstance(params, dict):
            print(f"  ** PARAMS NOT AN OBJECT — event would be dropped **"); bad += 1; continue
        try:
            svg = render(name, **params)
        except Exception as exc:
            print(f"  ** RENDER FAILED: {exc} **"); bad += 1; continue

        tags = set(re.findall(r"<([a-zA-Z][a-zA-Z0-9]*)", svg))
        drawn = tags & DRAWABLE
        banned = [b for b in BANNED if b in svg.lower()]
        texts = len(re.findall(r"<text", svg))
        ok = svg.startswith("<svg") and drawn and not banned and len(svg) > 200
        print(f"  svg: {len(svg)} chars, {len(drawn)} drawable kinds {sorted(drawn)}, {texts} labels")
        if banned:
            print(f"  ** BANNED CONSTRUCT: {banned} **")
        if not ok:
            print("  ** SVG FAILED THE BOARD CONTRACT **"); bad += 1; continue

        out_dir = os.environ.get("DIAGRAM_OUT", "/tmp")
        out = os.path.join(out_dir, f"diagram_{subject}.svg")
        open(out, "w").write(svg)
        print(f"  OK -> {out}")
    print(f"\n{len(CASES) - bad}/{len(CASES)} subjects produced a valid diagram")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
