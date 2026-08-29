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
import html
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

# How much diagram to draw. This is a pedagogical setting, not a size setting.
#
# "simple" is the DEFAULT and the one that matters. The brief came from a
# co-founder watching a session: "what if it's a weak student? He can't imagine
# like us." A strong student reads "the resultant is 5 N at 37 degrees" and sees
# it. A weak one needs the triangle drawn with 3, 4 and 5 written on it. So the
# job is not an impressive chapter illustration — it is the small concrete
# figure that would sit beside a worked example in a textbook. Think the figure
# next to a LaTeX example, not a plate.
#
# Small also means FAST: ~20 elements draws in about 2.4s against 7s for 70, so
# a simple diagram can appear beside almost every example instead of once a
# chapter. More diagrams, each doing less, is the goal.
DETAIL_LEVELS = {
    "simple": (
        "SCOPE — this is the most important rule here:\n"
        "Draw ONE small figure showing ONE concrete instance. Not a chapter overview,\n"
        "not a summary of everything, not a poster. The figure that would sit beside a\n"
        "single worked example in a textbook.\n"
        "- Aim for 12-25 elements TOTAL. Above 30 you are drawing the wrong thing.\n"
        "- Use REAL NUMBERS, not symbols, wherever a number would do. A triangle\n"
        "  labelled 3, 4, 5 teaches a struggling student more than one labelled a, b, c.\n"
        "- Canvas around 340x240, and never wider than 380. The board column on a\n"
        "  phone is about 300px, so a wide canvas scales down until the labels are\n"
        "  unreadable. Narrow and tall survives a phone; wide and short does not.\n"
        "- If the concept has several parts, draw the ONE that unlocks it and ignore\n"
        "  the rest. Another diagram can cover the others.\n"
        "- Assume the student CANNOT already picture this. That is why it exists.\n"
    ),
    "rich": (
        "SCOPE — a fuller figure, for a concept that genuinely needs one.\n"
        "- Up to 70 elements. Label every part a student must name.\n"
        "- Canvas around 420x300 — still phone-first. 520 wide scales to 0.58 on a\n"
        "  375px phone and takes every label under 10px with it.\n"
        "- Still one idea, drawn thoroughly, rather than several crammed together.\n"
    ),
}

# The style spec is the product decision in this module. Everything else is
# mechanism. This is what makes diagrams read as one system rather than a pile
# of drawings, so it is deliberately specific about weights and placement.
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
- Labels 15-17px. A title, if any, 19px. NEVER smaller than 14px.
  These look large next to a 340-wide canvas, and that is deliberate. The board
  scales the whole SVG down to fit its column, and on a 375px phone that column
  is about 300px — so a 13px label lands at roughly 8px on screen, which no
  student can read. Sizing for the phone first and letting it scale UP on
  desktop is the only ordering that works.
- COLOUR CARRIES MEANING, it is not decoration. Use one consistent contrast per
  diagram — e.g. red vs blue for oxygenated vs deoxygenated, green for the quantity
  being measured, amber for the thing the student must notice. Everything else is
  ink and muted.
- Leave 16px of margin. Nothing may touch the canvas edge.
- LABELS MUST NOT OVERLAP EACH OTHER. You cannot measure text, so leave room:
  assume every character is about 0.55 x the font-size wide, and keep at least
  one full line-height of vertical space between any two labels. A label that
  collides with its neighbour is the most common way a correct diagram looks
  broken, and the board lets overflow spill rather than clipping it.
- Put labels OUTSIDE the shape they name, with a short leader line, rather than
  crowding them inside. Prefer fewer, shorter labels over many long ones.
- NEVER draw a label on top of a FILLED shape. It vanishes into the fill once the
  board recolours it. Place it beside the shape and point with a leader line. A
  label inside an UNFILLED outline is fine.
- Label every part a student is expected to name. An unlabelled diagram teaches nothing.
- No shadows, no gradients, no opacity tricks. Flat, clean, chalk-on-paper.

Return ONLY the SVG. No prose, no markdown fence, no explanation."""


def spec_for(detail: str = "simple") -> str:
    """The style spec plus the scope rules for this detail level."""
    return STYLE_SPEC.replace(
        "Return ONLY the SVG.",
        DETAIL_LEVELS.get(detail, DETAIL_LEVELS["simple"]) + "\nReturn ONLY the SVG.",
    )



# Roughly how wide a character renders, as a fraction of font-size, for the
# sans-serif the board uses. Approximate on purpose — the exact font is Anek
# Latin, injected by the web app, and an author writing SVG cannot know its
# metrics. That uncertainty IS the bug: <text> has no layout, so the author
# guesses a width, and a wrong guess collides with the next label.
_CHAR_ADVANCE = 0.55
# Boxes must clear each other by this fraction of font-size before we call it
# a collision. Slightly forgiving, because the estimate above is.
_COLLISION_SLACK = 0.12


def _text_boxes(svg: str) -> List[Tuple[float, float, float, float, str]]:
    """Estimated bounding boxes for every <text>, in user units."""
    boxes = []
    for m in re.finditer(r"<text([^>]*)>(.*?)</text>", svg, re.S):
        attrs, body = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        # Measure the CHARACTERS, not the markup. "&#215;" is one glyph wide,
        # not six, and a diagram that writes a degree sign or a multiplication
        # cross was being rejected for a collision it did not have.
        body = html.unescape(body)
        if not body:
            continue

        def num(key: str, default: float) -> float:
            hit = re.search(rf'{key}="([-\d.]+)"', attrs)
            return float(hit.group(1)) if hit else default

        size = num("font-size", 14.0)
        anchor_m = re.search(r'text-anchor="(\w+)"', attrs)
        anchor = anchor_m.group(1) if anchor_m else "start"
        width = len(body) * size * _CHAR_ADVANCE
        x, y = num("x", 0.0), num("y", 0.0)
        if anchor == "middle":
            x -= width / 2
        elif anchor == "end":
            x -= width
        pad = size * _COLLISION_SLACK
        boxes.append((x + pad, y - size * 0.8 + pad,
                      x + width - pad, y + size * 0.25 - pad, body))
    return boxes


# Fills a label can legibly sit on. These are backing panels — a boxed formula
# on pale grey is a deliberate, correct pattern, not a defect, and rejecting it
# would throw away most good diagrams. Everything else is saturated enough that
# ink-coloured text on it is genuinely hard to read.
PALE_FILLS = {"#ffffff", "#f1f5f9", "#dbeafe"}


def _filled_boxes(svg: str) -> List[Tuple[float, float, float, float]]:
    """Boxes of shapes whose fill would swallow a label.

    Only rect: it is what templates and authored figures use as panels, and a
    path's bounding box cannot be computed without a geometry engine.

    PALE fills are excluded deliberately. The first version of this flagged any
    fill at all and rejected 7 of 8 real diagrams — including boxed formulas on
    pale grey, which are correct and wanted. The hazard is contrast, not the
    existence of a fill.
    """
    boxes = []
    for m in re.finditer(r"<rect([^>]*)>", svg):
        a = m.group(1)
        fill = re.search(r'fill="([^"]+)"', a)
        if not fill or fill.group(1).lower() in PALE_FILLS | {"none", "transparent"}:
            continue

        def n(k, d=0.0):
            hit = re.search(rf'{k}="([-\d.]+)"', a)
            return float(hit.group(1)) if hit else d

        w, h = n("width"), n("height")
        if w <= 0 or h <= 0:
            continue
        # A full-canvas background rect is not an overlap hazard.
        if w * h > 100000:
            continue
        boxes.append((n("x"), n("y"), n("x") + w, n("y") + h))
    return boxes


def labels_over_shapes(svg: str) -> List[str]:
    """Labels drawn on top of a filled shape.

    Prompted by a report from a live class, though not the same thing as it:
    that case was ink on a PALE panel, which restyles to dark-on-cream and reads
    fine. It was crowding the scale bar it named, which is a spec matter — the
    style rules now say to put a label beside a shape with a leader line.

    What this catches is the harder failure: a label on a SATURATED fill, where
    the text does not just crowd but disappears once the board recolours it, and
    the app is forbidden from moving it.
    """
    hits = []
    for tb in _text_boxes(svg):
        tx0, ty0, tx1, ty1, body = tb
        cx, cy = (tx0 + tx1) / 2, (ty0 + ty1) / 2
        for bx0, by0, bx1, by1 in _filled_boxes(svg):
            # Centre inside a filled box: the label is ON the panel, not beside it.
            if bx0 < cx < bx1 and by0 < cy < by1:
                hits.append(body)
                break
    return hits


def colliding_labels(svg: str) -> List[Tuple[str, str]]:
    """Pairs of labels whose estimated boxes overlap.

    Overlapping text is the single most common way an otherwise correct diagram
    looks wrong, and the board makes it worse rather than better: it sets
    overflow="visible" so labels that outgrow the viewBox spill over their
    neighbours instead of being clipped.
    """
    boxes = _text_boxes(svg)
    hits = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]):
                hits.append((a[4][:24], b[4][:24]))
    return hits


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
    over = labels_over_shapes(svg)
    if over:
        return False, ("labels drawn over filled shapes: "
                       + ", ".join(repr(o) for o in over[:3]))
    clashes = colliding_labels(svg)
    if clashes:
        # Rejected so the retry loop redraws it, which is the only fix that
        # scales — asking the spec more politely does not stop a model from
        # mis-estimating a text width it cannot measure.
        shown = "; ".join(f"{a!r} over {b!r}" for a, b in clashes[:3])
        return False, f"{len(clashes)} overlapping labels ({shown})"
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
    detail: str = "simple",
) -> Tuple[Optional[str], str]:
    """Author one SVG for this concept. Returns (svg or None, reason).

    `detail` is "simple" by default — a small concrete figure for one instance,
    which is what a student who cannot already picture the idea actually needs.
    "rich" is for the rare concept that genuinely warrants a full illustration.

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
        messages = [{"role": "system", "content": spec_for(detail)},
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
