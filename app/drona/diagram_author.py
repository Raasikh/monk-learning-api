"""Author a board diagram as SVG, and refuse anything the board cannot draw.

WHY THIS EXISTS ALONGSIDE diagram_templates.py
==============================================
Templates take PARAMETERS. This takes a TOPIC and what is being explained about
it. That difference is the whole point: a template knows the shape of a free
body diagram but cannot know that this segment is about why the left ventricle
wall is thickest. An authored diagram can emphasise exactly that.

Templates also have a hard ceiling. They are assembled from lines and boxes, so
they produce schematics. `path` is an allowed primitive on the board, which
means Bezier curves are available and an anatomically drawn heart is possible —
just not from a parameterised template. Measured: a hand-authored heart came in
at 2.6KB, fully contract-clean, and no template in the library can produce it.

THREE TIERS, FASTEST FIRST
==========================
  1. PRECOMPUTED — authored once at plan time, stored, replayed instantly.
  2. TEMPLATE    — a cue fires and a template genuinely fits. ~0.1ms.
  3. LIVE        — a novel doubt nobody anticipated. Measured 4.4-10.4s, run in
     parallel with the turn and raced against the sentence that introduces it.

Tier 3 is affordable only because the board reveals progressively: a diagram
tied to seq 3 is not needed until the third sentence plays, which is 10-20s in.
If it loses the race it is dropped and the lesson continues without it. A
missing diagram is a plainer lesson; a blocked turn is a broken one.

VALIDATION IS NOT OPTIONAL
==========================
Every failure mode of this board is SILENT. A non-drawable element simply never
appears. An off-palette colour survives restyling and clashes. A <marker>
arrowhead pops in before the line it belongs to. So nothing authored reaches a
student without passing validate(), and a rejection costs a picture rather than
a lesson — the same posture _materialise_template already takes.
"""
import logging
import re
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

from app.drona.diagram_templates import ALLOWED_COLORS, MAX_SVG_CHARS
from app.drona.models import get_drona_client, get_model_name

logger = logging.getLogger("drona.diagram_author")

# Exactly what buildDrawPlan in PremiumBoardEvent.tsx walks and animates.
DRAWABLE = {"path", "line", "polyline", "polygon", "circle", "ellipse", "rect"}
# text is allowed but fades rather than draws, so it is permitted and not
# counted as drawable.
ALLOWED_TAGS = DRAWABLE | {"svg", "text", "tspan", "g"}
BANNED_SUBSTRINGS = (
    "<script", "<defs", "<marker", "<image", "<foreignobject", "<use",
    "xlink:href", "href=", "font-family", "javascript:",
)
BANNED_ATTR = re.compile(r"\son[a-z]+\s*=", re.I)

# The cap that actually matters. PremiumBoardEvent draws each element in turn
# with `dur = max(60, TOTAL_BUDGET / steps)`, so once steps exceed
# TOTAL_BUDGET/60 the floor takes over and the draw stretches linearly. With the
# budget at 7000ms that ceiling is ~116 steps; 110 leaves headroom and keeps a
# diagram drawing in about the time a sentence takes to speak.
#
# Text counts. It fades rather than draws, but it is still a step in the plan.
MAX_DRAW_STEPS = 110

# The style spec is the product decision in this module. Everything else is
# mechanism. This is what makes nine diagrams read as one system rather than
# nine drawings, so it is deliberately specific about weights and placement.
STYLE_SPEC = f"""You draw ONE static SVG for a live tutoring whiteboard for Indian JEE/NEET students.

HARD RULES — an SVG breaking any of these is discarded and the student sees nothing:
- Elements allowed: path, line, polyline, polygon, circle, ellipse, rect, text, g.
- FORBIDDEN: <defs>, <marker>, <script>, <image>, <foreignObject>, <use>, any href
  or xlink:href, any on* attribute, and any font-family attribute.
- Colours ONLY from this palette, exact hex:
    #1f2933 ink (outlines, default text)      #64748b muted (secondary labels, guides)
    #2563eb blue                              #dbeafe pale blue (fills)
    #dc2626 red                               #059669 green
    #d97706 amber                             #f1f5f9 pale grey (fills)
    #ffffff background
- Open with <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 W H"> and make the
  FIRST child a white background rect covering the canvas.
- Under {MAX_SVG_CHARS - 1500} characters AND under {MAX_DRAW_STEPS - 10} total
  elements (every shape plus every text counts). The board draws them one at a
  time, so a diagram with 200 elements takes far too long to appear. Prefer
  fewer, better-chosen strokes over exhaustive detail.

DRAW ORDER IS ANIMATION ORDER. The board draws each stroke in document order, so
emit in the order a teacher draws: container or outline first, then internal
structure, then arrows, then labels last. Never a label before the thing it names.

ARROWHEADS are explicit <polygon> emitted immediately after their line. Markers are
stripped, so a marker arrowhead would appear before its own arrow.

STYLE — hold to these so every diagram reads as one system:
- Outlines 2.4-3 stroke-width. Internal structure 2. Guides and dashed leaders 1.4.
- Labels 11-13px. A title, if any, 14px. Never smaller than 10px.
- COLOUR CARRIES MEANING, it is not decoration. Use one consistent contrast per
  diagram — e.g. red vs blue for oxygenated vs deoxygenated, green for the quantity
  being measured, amber for the thing the student must notice. Everything else is
  ink and muted.
- Leave 16px of margin. Nothing may touch the canvas edge.
- Label every part a student is expected to name. An unlabelled diagram teaches nothing.
- No shadows, no gradients, no opacity tricks. Flat, clean, chalk-on-paper.

Return ONLY the SVG. No prose, no markdown fence, no explanation."""


def validate(svg: str) -> Tuple[bool, str]:
    """(ok, reason). Cheap, total, and the only thing standing between a model's
    output and a student's screen."""
    if not svg or not svg.lstrip().startswith("<svg"):
        return False, "does not start with <svg"
    if len(svg) > MAX_SVG_CHARS:
        return False, f"{len(svg)} chars over the {MAX_SVG_CHARS} budget"
    low = svg.lower()
    for banned in BANNED_SUBSTRINGS:
        if banned in low:
            return False, f"contains {banned}"
    if BANNED_ATTR.search(svg):
        return False, "contains an on* event attribute"
    if not re.search(r'viewBox="[\d.\s-]+"', svg):
        return False, "no explicit viewBox"
    try:
        ET.fromstring(svg)
    except ET.ParseError as exc:
        return False, f"not well-formed XML: {exc}"
    tags = {t.split("}")[-1] for t in re.findall(r"<([a-zA-Z][a-zA-Z0-9]*)", svg)}
    stray = tags - ALLOWED_TAGS
    if stray:
        return False, f"undrawable elements: {sorted(stray)}"
    if not (tags & DRAWABLE):
        return False, "nothing drawable — text only"
    steps = sum(len(re.findall(rf"<{t}\b", svg)) for t in DRAWABLE)
    steps += len(re.findall(r"<text\b", svg))
    if steps > MAX_DRAW_STEPS:
        # Not a size problem — a pacing one. Past this the per-step floor makes
        # the diagram draw for longer than the sentence introducing it.
        return False, f"{steps} draw steps over the {MAX_DRAW_STEPS} limit"
    used = {m.lower() for m in re.findall(r"#[0-9a-fA-F]{6}", svg)}
    off = used - {c.lower() for c in ALLOWED_COLORS}
    if off:
        return False, f"off-palette colours: {sorted(off)}"
    return True, ""


def _strip_fence(text: str) -> str:
    out = (text or "").strip()
    out = re.sub(r"^```[a-zA-Z]*\s*", "", out)
    out = re.sub(r"```\s*$", "", out)
    # Models occasionally prepend a sentence despite being told not to.
    i = out.find("<svg")
    return out[i:].strip() if i > 0 else out.strip()


def author_diagram(
    subject: str,
    concept: str,
    explanation: str = "",
    *,
    attempts: int = 2,
    model: Optional[str] = None,
    timeout: int = 90,
) -> Tuple[Optional[str], str]:
    """Author one SVG for this concept. Returns (svg or None, reason).

    `explanation` is what makes this better than a template — pass the teaching
    notes or the student's actual question, and the diagram is drawn for THAT
    rather than for the topic in general.

    Retries once on a validation failure, feeding the reason back. Never raises:
    a diagram is an enhancement, and the caller must be able to carry on without
    one.
    """
    client = get_drona_client()
    model_name = model or get_model_name("tutor")
    ask = (f"Subject: {subject}\nConcept: {concept}\n"
           f"{('What is being explained: ' + explanation) if explanation else ''}\n\n"
           f"Draw the diagram that makes this concept click for a student seeing it "
           f"for the first time.")
    last = "no attempt made"
    for attempt in range(1, attempts + 1):
        messages = [{"role": "system", "content": STYLE_SPEC},
                    {"role": "user", "content": ask}]
        if attempt > 1:
            messages.append({
                "role": "user",
                "content": f"Your previous SVG was rejected: {last}. "
                           f"Return a corrected SVG obeying every rule.",
            })
        try:
            res = client.chat.completions.create(
                model=model_name, messages=messages, temperature=0.2,
                max_tokens=3500, timeout=timeout,
                extra_body={"thinking": {"type": "disabled"}},
            )
            svg = _strip_fence(res.choices[0].message.content or "")
        except Exception as exc:
            last = f"call failed: {exc}"
            logger.warning(f"[DIAGRAM AUTHOR] {concept!r} attempt {attempt}: {last}")
            continue
        ok, reason = validate(svg)
        if ok:
            logger.info(f"✏️ [DIAGRAM AUTHORED] {concept!r} ({len(svg)} chars, attempt {attempt})")
            return svg, ""
        last = reason
        logger.warning(f"[DIAGRAM REJECTED] {concept!r} attempt {attempt}: {reason}")
    return None, last
