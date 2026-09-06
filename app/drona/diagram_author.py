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
from app.drona.models import get_drona_client, get_model_name, thinking_off

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
        "- Canvas around 640x260, and never narrower than 560 wide. The board is\n"
        "  LANDSCAPE and about 700pt wide by 250pt tall, so a square-ish canvas\n"
        "  fits to height and leaves half the board empty. Wide and short is what\n"
        "  this board wants; narrow and tall wastes it.\n"
        "- If the concept has several parts, draw the ONE that unlocks it and ignore\n"
        "  the rest. Another diagram can cover the others.\n"
        "- Assume the student CANNOT already picture this. That is why it exists.\n"
    ),
    "rich": (
        "SCOPE — a fuller figure, for a concept that genuinely needs one.\n"
        "- Up to 70 elements. Label every part a student must name.\n"
        "- Canvas around 760x300 — landscape-first, matching the board's own shape.\n"
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
  On a 640-wide canvas drawn into a ~700pt landscape board the SVG renders at
  roughly 1:1, so these are close to their on-screen point size. Do not shrink
  them on the theory that the board will scale them up — it will not.
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
# How far a label may hang past the viewBox before it counts as stray.
_BOUNDS_SLACK = 6.0


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
    if not svg or not svg.strip():
        # DISTINCT from a formatting failure, and it matters: an empty response
        # means the CALL failed (bad model id, filtered, truncated), while
        # "does not start with <svg" means the model answered and we could not
        # parse it. Reporting the second for the first sent a whole chapter's
        # diagram loss to the wrong diagnosis -- the fix looked like string
        # handling when it was a model id.
        return False, "model returned an EMPTY response (call failed, not a formatting problem)"
    if not svg.lstrip().startswith("<svg"):
        return False, f"does not start with <svg (got {svg.lstrip()[:40]!r})"
    if len(svg) > MAX_SVG_CHARS:
        return False, f"{len(svg)} chars over the {MAX_SVG_CHARS} budget"
    low = svg.lower()
    for banned in BANNED_SUBSTRINGS:
        if banned in low:
            return False, f"contains {banned}"
    if BANNED_ATTR.search(svg):
        return False, "contains an on* event attribute"
    vb = re.search(r'viewBox="[\d.-]+\s+[\d.-]+\s+([\d.]+)\s+([\d.]+)"', svg)
    if not vb:
        return False, "no explicit viewBox"
    vb_w, vb_h = float(vb.group(1)), float(vb.group(2))
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

    # A label placed outside the viewBox is not clipped — the clients are told
    # not to clip, because a label may legitimately sit a hair over the edge —
    # so it renders on top of whatever the board puts beside the figure. Two
    # templates did exactly this, by up to 19px, and nothing caught it. The
    # tolerance is deliberate: the width estimate above is approximate, and a
    # few pixels of overhang is the case the no-clip rule exists for.
    strays = [t for x0, y0, x1, y1, t in _text_boxes(svg)
              if x0 < -_BOUNDS_SLACK or y0 < -_BOUNDS_SLACK
              or x1 > vb_w + _BOUNDS_SLACK or y1 > vb_h + _BOUNDS_SLACK]
    if strays:
        return False, f"{len(strays)} labels outside the viewBox ({strays[0][:28]!r})"
    return True, ""


# ---------------------------------------------------------------------------
# LAYOUT POST-PASS
# ---------------------------------------------------------------------------
# Runs between _strip_fence() and validate(), which is the ONE place every
# authored SVG passes through on its way to the gate. There is no SVGO or other
# third-party normaliser in this repo — _strip_fence is the whole normalisation
# stage — so this sits immediately after it rather than becoming a second
# pipeline nobody remembers to call.
#
# WHY A REPAIR AND NOT ANOTHER PROMPT RULE
# The spec already tells the model to keep labels apart and inside the canvas.
# It cannot obey: <text> has no layout, so the model is estimating a width it
# cannot measure. Asking more politely does not fix arithmetic. These three
# failures are the ones a deterministic pass CAN fix, so it fixes them.
#
# WHAT IT MUST NOT DO
# It never touches the drawing. Only <text> x/y and the font-family attribute.
# If a label can only be saved by moving a path, that is out of scope and the
# SVG is returned UNCHANGED so validate() rejects it loudly. A silently-worse
# layout that passes is the failure mode this whole module exists to avoid.

# The gate's own text metrics, mirrored from the mobile render gate
# (monklearning-mobile/scripts/verify-render.mjs, textBox()/overlaps()).
#
# These are DELIBERATELY not _CHAR_ADVANCE/_COLLISION_SLACK above. That model
# (0.55 wide, inset by 0.12*size) produces a STRICTLY SMALLER box than the
# render gate's (0.58 wide, no inset, taller). Repairing to the smaller box
# would leave the render gate still rejecting the result. Repairing to the
# larger box satisfies both, because the smaller box is contained in it — the
# repair is narrower than either gate, never wider.
_GATE_CHAR_W = 0.58      # verify-render.mjs: w = s.length * size * 0.58
_GATE_ASCENT = 0.82      # verify-render.mjs: y0 = y - size * 0.82
_GATE_LINE_H = 1.15      # verify-render.mjs: h = size * 1.15

# Clear a repaired pair by this much beyond bare contact. Both gates test
# overlap with a strict inequality, so touching already passes; the margin is
# for the float arithmetic and for the difference between the two box models.
_REPAIR_GAP = 1.5
# Keep repaired labels this far inside the viewBox. validate() allows 6px of
# overhang (_BOUNDS_SLACK); we spend none of it, so a clamped label is inside
# the canvas under any reading.
_REPAIR_INSET = 1.0
# Fixed-point cap. Each round re-derives every box after every move, so a
# crowded layout walks toward a solution a pair at a time: six mutually
# overlapping labels take 11 rounds. The cap is set well above that ON PURPOSE
# — it exists to stop a cycle, not to decide repairability. If a layout is
# still moving at 40 the viewBox has no room for it, and that is a geometric
# verdict rather than an exhausted budget. Rounds are O(labels^2) over ~20
# labels, so the whole budget is microseconds.
_MAX_REPAIR_ROUNDS = 40

_TEXT_RE = re.compile(r"<text([^>]*)>(.*?)</text>", re.S)


def _gate_box(x: float, y: float, size: float, anchor: str, body: str):
    """The render gate's box for one label. Mirrors verify-render.mjs textBox()."""
    w = len(body) * size * _GATE_CHAR_W
    x0 = x - w / 2 if anchor == "middle" else (x - w if anchor == "end" else x)
    y0 = y - size * _GATE_ASCENT
    return x0, y0, x0 + w, y0 + size * _GATE_LINE_H


def _gate_overlaps(a, b) -> bool:
    """verify-render.mjs overlaps(). TRUE for two identical boxes."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _parse_texts(svg: str):
    """Every <text> with its anchor point and metrics, in document order."""
    out = []
    for m in _TEXT_RE.finditer(svg):
        attrs, raw = m.group(1), m.group(2)
        body = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        if not body:
            continue

        def num(key, default):
            hit = re.search(rf'{key}="([-\d.]+)"', attrs)
            return float(hit.group(1)) if hit else default

        anchor_m = re.search(r'text-anchor="(\w+)"', attrs)
        out.append({
            "span": m.span(), "attrs": attrs,
            "x": num("x", 0.0), "y": num("y", 0.0),
            "size": num("font-size", 14.0),
            "anchor": anchor_m.group(1) if anchor_m else "start",
            "body": body,
        })
    return out


def _rewrite_text_positions(svg: str, texts) -> str:
    """Write x/y back onto each <text>. Only x and y — nothing else is touched."""
    out, cursor = [], 0
    for t in texts:
        start, end = t["span"]
        out.append(svg[cursor:start])
        attrs = t["attrs"]
        for key, val in (("x", t["x"]), ("y", t["y"])):
            new = f'{key}="{val:g}"'
            if re.search(rf'\s{key}="[-\d.]+"', attrs):
                attrs = re.sub(rf'\s{key}="[-\d.]+"', " " + new, attrs, count=1)
            else:
                attrs = attrs + " " + new
        body = svg[start:end]
        inner = body[body.index(">") + 1:]
        out.append(f"<text{attrs}>{inner}")
        cursor = end
    out.append(svg[cursor:])
    return "".join(out)


def strip_font_family(svg: str) -> Tuple[str, bool]:
    """Remove every font-family declaration. Unconditional.

    validate() bans the substring anywhere, so both spellings go: the attribute
    and the CSS property inside a style="". If the literal survives both — it is
    in label TEXT, say, a diagram about typography — nothing here can remove it
    without changing what the diagram says, and the caller reports it.
    """
    before = svg
    svg = re.sub(r'\s*font-family\s*=\s*"[^"]*"', "", svg, flags=re.I)
    svg = re.sub(r"\s*font-family\s*=\s*'[^']*'", "", svg, flags=re.I)
    svg = re.sub(r"\s*font-family\s*:[^;\"'}]*;?", "", svg, flags=re.I)
    return svg, svg != before


def _violations(svg: str, vb_w: float, vb_h: float):
    """(stray label indices, overlapping index pairs, on-fill indices).

    Measured with the RENDER GATE's box, which contains validate()'s, so a
    layout clean here is clean under both.
    """
    texts = _parse_texts(svg)
    boxes = [_gate_box(t["x"], t["y"], t["size"], t["anchor"], t["body"]) for t in texts]
    strays = [i for i, b in enumerate(boxes)
              if b[0] < 0 or b[1] < 0 or b[2] > vb_w or b[3] > vb_h]
    pairs = [(i, j) for i in range(len(boxes)) for j in range(i + 1, len(boxes))
             if _gate_overlaps(boxes[i], boxes[j])]
    fills = _filled_boxes(svg)
    on_fill = []
    for i, b in enumerate(boxes):
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        if any(f[0] < cx < f[2] and f[1] < cy < f[3] for f in fills):
            on_fill.append(i)
    return strays, pairs, on_fill


def repair_layout(svg: str) -> Tuple[str, dict]:
    """Deterministically repair the layout failures validate() can see.

    Returns (svg, report). The report is the point: it names what was repaired,
    what resisted, and — separately — the case of a diagram with no labels at
    all, which is NOT a clean layout. A checker that reports "0 overlaps, pass"
    on a diagram with nothing to overlap has told you nothing, and this codebase
    has shipped that mistake before.

    The repaired SVG is returned ONLY if every layout violation is gone. A
    partial repair is discarded and the original returned, so validate() fails
    on the real reason instead of passing a layout that is merely differently
    broken.
    """
    report = {"font_family_stripped": False, "font_family_unrepairable": False,
              "labels": 0, "no_labels": False,
              "strays_before": 0, "overlaps_before": 0, "on_fill_before": 0,
              "rounds": 0, "converged": False, "applied": False,
              "unrepairable": []}

    svg, stripped = strip_font_family(svg)
    report["font_family_stripped"] = stripped
    if "font-family" in svg.lower():
        # Survived both rewrites: it is inside label text or an entity, and
        # removing it would change what the diagram says.
        report["font_family_unrepairable"] = True
        report["unrepairable"].append("font-family in text content")

    vb = re.search(r'viewBox="[\d.-]+\s+[\d.-]+\s+([\d.]+)\s+([\d.]+)"', svg)
    if not vb:
        report["unrepairable"].append("no viewBox — cannot clamp")
        return svg, report
    vb_w, vb_h = float(vb.group(1)), float(vb.group(2))

    texts = _parse_texts(svg)
    report["labels"] = len(texts)
    if not texts:
        # Its own category, deliberately. "No labels" is a diagram that teaches
        # nothing, not a diagram whose labels are all correctly placed.
        report["no_labels"] = True
        report["converged"] = True
        return svg, report

    s0, p0, f0 = _violations(svg, vb_w, vb_h)
    report["strays_before"] = len(s0)
    report["overlaps_before"] = len(p0)
    report["on_fill_before"] = len(f0)
    if not (s0 or p0 or f0):
        report["converged"] = True
        return svg, report

    # A label wider than the whole canvas cannot be clamped into it. The only
    # fixes are a smaller font or a wider viewBox, and both are the drawing.
    for t in texts:
        b = _gate_box(t["x"], t["y"], t["size"], t["anchor"], t["body"])
        if b[2] - b[0] > vb_w or b[3] - b[1] > vb_h:
            report["unrepairable"].append(
                f"label {t['body'][:24]!r} is wider than the {vb_w:g}x{vb_h:g} viewBox")
            return svg, report

    work = [dict(t) for t in texts]
    fills = _filled_boxes(svg)

    def boxes_of(ts):
        return [_gate_box(t["x"], t["y"], t["size"], t["anchor"], t["body"]) for t in ts]

    def clamp(ts):
        for t in ts:
            x0, y0, x1, y1 = _gate_box(t["x"], t["y"], t["size"], t["anchor"], t["body"])
            if x0 < _REPAIR_INSET:
                t["x"] += _REPAIR_INSET - x0
            elif x1 > vb_w - _REPAIR_INSET:
                t["x"] -= x1 - (vb_w - _REPAIR_INSET)
            if y0 < _REPAIR_INSET:
                t["y"] += _REPAIR_INSET - y0
            elif y1 > vb_h - _REPAIR_INSET:
                t["y"] -= y1 - (vb_h - _REPAIR_INSET)

    for rnd in range(1, _MAX_REPAIR_ROUNDS + 1):
        report["rounds"] = rnd
        clamp(work)
        boxes = boxes_of(work)

        moved = False
        # Overlaps: nudge along the MINOR axis. A label is wide and short, so
        # its minor axis is vertical. Sliding it sideways is what walks a label
        # away from the thing it names; a line-height up or down keeps it beside
        # its own shape.
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if not _gate_overlaps(a, b):
                    continue
                depth = min(a[3], b[3]) - max(a[1], b[1]) + _REPAIR_GAP
                up, down = (i, j) if (a[1] + a[3]) <= (b[1] + b[3]) else (j, i)
                work[up]["y"] -= depth / 2
                work[down]["y"] += depth / 2
                moved = True
                boxes = boxes_of(work)

        # A label sitting ON a saturated fill needs to come OFF it — the same
        # vertical move, to whichever edge of the panel is nearer. This class was
        # not in the original brief; it turns up in the live run, and the minor
        # axis handles it for the same reason it handles an overlap.
        for i, b in enumerate(boxes):
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            hit = next((f for f in fills if f[0] < cx < f[2] and f[1] < cy < f[3]), None)
            if not hit:
                continue
            h = b[3] - b[1]
            work[i]["y"] += (hit[1] - _REPAIR_GAP - h / 2 - cy) if (cy - hit[1]) < (hit[3] - cy) \
                else (hit[3] + _REPAIR_GAP + h / 2 - cy)
            moved = True
            boxes = boxes_of(work)

        if not moved:
            clamp(work)
            candidate = _rewrite_text_positions(svg, work)
            s, p, f = _violations(candidate, vb_w, vb_h)
            if not (s or p or f):
                report["converged"] = True
                report["applied"] = True
                return candidate, report
            break

    # Did not reach a fixed point, or reached one that is still in violation.
    # Return the ORIGINAL. A half-nudged layout that squeaks past the gate is
    # worse than a rejection, because the rejection triggers a redraw.
    s, p, f = _violations(_rewrite_text_positions(svg, work), vb_w, vb_h)
    report["unrepairable"].append(
        f"no fixed point in {report['rounds']} rounds "
        f"({report['overlaps_before']} overlaps, {report['strays_before']} strays, "
        f"{report['on_fill_before']} on-fill in; {len(p)}/{len(s)}/{len(f)} left)")
    return svg, report


def _strip_fence(text: str) -> str:
    out = (text or "").strip()
    out = re.sub(r"^```[a-zA-Z]*\s*", "", out)
    out = re.sub(r"```\s*$", "", out)
    # Models occasionally prepend a sentence despite being told not to.
    i = out.find("<svg")
    if i > 0:
        out = out[i:]
    out = out.strip()
    # And append one AFTER the drawing, despite the same instruction. The
    # closing fence is then no longer at the end of the string, so the rule
    # above does not match it, and the prose plus a stray ``` stay glued to the
    # document. validate() reports that as "not well-formed XML ... line N,
    # column 0", which reads exactly like a truncated response and was diagnosed
    # as one — it is the opposite, a response with too much in it. Measured on a
    # 20-attempt biology sample: every such failure had finish_reason="stop" and
    # a complete </svg>, and 3 of 4 passed the gate untouched once the tail was
    # cut. Keep everything up to the LAST </svg>; if there is no </svg> the
    # response really was cut short, and it is left alone to fail loudly rather
    # than be closed up into a diagram missing its bottom half.
    end = out.rfind("</svg>")
    return out[:end + 6] if end != -1 else out


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
                extra_body=thinking_off(),
            )
            raw = res.choices[0].message.content or ""
            finish = getattr(res.choices[0], "finish_reason", None) or "?"
            # TRUNCATION AND REFUSAL LOOK IDENTICAL DOWNSTREAM. Both end up as
            # validate()'s "does not start with <svg", which reports the first
            # 40 characters and explains nothing:
            #
            #   attempt 1: does not start with <svg
            #              (got 'I'll generate a clean teaching SVG that ')
            #
            # That is a model which opened with a preamble and then ran out of
            # budget mid-sentence -- _strip_fence already removes a preamble
            # that PRECEDES a drawing, so reaching validate() in this shape
            # means there is no <svg in the response at all. finish_reason is
            # the only field that separates "never drew it" from "was cut off",
            # and nothing on this path was capturing it. Same gap, same fix, as
            # the segment path in planner.py.
            if finish == "length" and "<svg" not in raw:
                last = (f"TRUNCATED before any <svg: {len(raw)} chars at "
                        f"max_tokens, finish_reason=length. The preamble ate "
                        f"the budget; this is not a drawing failure.")
                logger.warning(f"[DIAGRAM TRUNCATED] {concept!r} attempt {attempt}: {last}")
                continue
            svg = _strip_fence(raw)
            # Deterministic layout repair BEFORE the gate. _strip_fence is the
            # only normalisation this module has, so the post-pass goes right
            # after it — one place, on the one path every authored SVG takes.
            svg, fix = repair_layout(svg)
            if fix["no_labels"] and svg:
                logger.info(f"[DIAGRAM UNLABELLED] {concept!r} attempt {attempt}: "
                            f"no <text> at all — nothing to lay out")
            elif fix["applied"] or fix["font_family_stripped"]:
                logger.info(
                    f"[DIAGRAM REPAIRED] {concept!r} attempt {attempt}: "
                    f"{fix['strays_before']} stray / {fix['overlaps_before']} overlapping / "
                    f"{fix['on_fill_before']} on-fill labels, font-family "
                    f"{'stripped' if fix['font_family_stripped'] else 'absent'}, "
                    f"{fix['rounds']} round(s)")
            elif fix["unrepairable"]:
                logger.info(f"[DIAGRAM UNREPAIRABLE] {concept!r} attempt {attempt}: "
                            f"{'; '.join(fix['unrepairable'])[:120]}")
        except Exception as exc:
            last = f"call failed: {exc}"
            logger.warning(f"[DIAGRAM AUTHOR] {concept!r} attempt {attempt}: {last}")
            continue
        ok, reason = validate(svg)
        if ok:
            logger.info(f"✏️ [DIAGRAM AUTHORED] {concept!r} ({len(svg)} chars, attempt {attempt})")
            return svg, ""
        last = reason
        logger.warning(f"[DIAGRAM REJECTED] {concept!r} attempt {attempt}: {reason} "
                       f"(finish_reason={finish})")
    return None, last
