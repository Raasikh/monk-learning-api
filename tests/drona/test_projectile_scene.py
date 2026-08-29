"""The first ILLUSTRATIVE template, and the board contract it has to honour.

Every other template draws a relationship — arrows, boxes, tables, flows.
This one draws the situation, because for projectile motion the situation is
the insight: fire one ball horizontally and drop another at the same instant,
and they hit the ground together. `vector_resolution` was what this content
got, and an arrow triangle cannot show that.

The contract in diagram_templates.py is strict and its failures are silent — a
non-drawable element simply never appears, an off-palette colour clashes with
the chalk board, a <marker> arrowhead pops in before its own line. So the
contract is asserted here rather than trusted.
"""

import math
import re

import pytest

from app.drona.diagram_templates import MAX_SVG_CHARS, TEMPLATES, render
from app.drona.tutor import suggest_diagram_template

DRAWABLE = {"path", "line", "polyline", "polygon", "circle", "ellipse", "rect"}
PALETTE = {"#1f2933", "#2563eb", "#dbeafe", "#64748b",
           "#d97706", "#dc2626", "#059669", "#f1f5f9", "#ffffff"}


def svg(**kw) -> str:
    base = dict(launch_label="u", angle_deg=45, range_label="R",
                height_label="H", show_dropped_ball=True)
    base.update(kw)
    return render("projectile_scene", **base)


def test_it_is_registered():
    assert "projectile_scene" in TEMPLATES


# ── the board contract ───────────────────────────────────────────────────────

def test_only_drawable_primitives_are_emitted():
    """Anything outside this set is skipped by buildDrawPlan and never appears."""
    tags = set(re.findall(r"<([a-zA-Z][a-zA-Z0-9]*)", svg()))
    assert tags & DRAWABLE, "nothing drawable in the output"
    assert not (tags - DRAWABLE - {"svg", "text", "tspan"}), f"undrawable: {tags - DRAWABLE}"


def test_no_defs_markers_or_external_references():
    """Marker internals are excluded from the draw plan, so a marker arrowhead
    appears before the line it belongs to. Arrowheads must be explicit polygons.
    """
    out = svg().lower()
    for banned in ("<defs", "<marker", "<script", "onload=", "<image",
                   "<foreignobject", "xlink:href", "font-family"):
        assert banned not in out, f"emits {banned}"


def test_every_colour_is_one_the_board_can_restyle():
    """An unmapped hex passes through untouched and clashes with the palette."""
    used = {m.lower() for m in re.findall(r"#[0-9a-fA-F]{6}", svg())}
    assert not (used - PALETTE), f"off-palette: {used - PALETTE}"


def test_it_has_a_viewbox_and_fits_the_websocket_budget():
    out = svg()
    assert re.search(r'viewBox="0 0 [\d.]+ [\d.]+"', out)
    assert len(out) < MAX_SVG_CHARS


def test_ground_is_drawn_before_the_arc():
    """Document order IS animation order — a teacher draws the ground first."""
    out = svg()
    assert out.index("<line") < out.index("<polyline"), "arc drawn before the ground"


# ── what the diagram actually teaches ────────────────────────────────────────

def test_the_dropped_ball_markers_are_level_with_the_projectile():
    """The claim being taught, asserted geometrically."""
    out = svg(show_dropped_ball=True)
    ys = [round(float(m), 2) for m in re.findall(r'<circle[^>]*cy="([\d.]+)"', out)]
    assert len(ys) == 8, f"expected 4 paired markers, got {len(ys)}"
    for y in set(ys):
        assert ys.count(y) == 2, f"height {y} is not paired between the two balls"


def test_the_dropped_ball_never_rises():
    """This test found a real physics error in the template, not the reverse.

    The first version placed markers at equal fractions along an ANGLED arc.
    A 45 degree trajectory is symmetric, so frac 0.25 and 0.75 have the same
    height — which put the "dropped" ball at one height twice and drew it going
    UP and back down. A dropped ball falls monotonically, always.

    The comparison is only true for a horizontal launch, so show_dropped_ball
    now switches to that scene rather than overlaying a drop on any arc.
    """
    out = svg(show_dropped_ball=True)
    ys = [round(float(m), 2) for m in re.findall(r'<circle[^>]*cy="([\d.]+)"', out)]
    heights = ys[::2]  # one per pair, in draw order
    assert heights == sorted(heights), f"the ball rises at some point: {heights}"
    # and the gaps widen, because y goes as t squared
    gaps = [b - a for a, b in zip(heights, heights[1:])]
    assert gaps == sorted(gaps), f"free fall must accelerate, gaps were {gaps}"


def test_the_comparison_can_be_turned_off():
    plain = svg(show_dropped_ball=False)
    assert "dropped" not in plain
    assert "<circle" not in plain, "no ball markers without the comparison"
    assert "<polyline" in plain, "the trajectory must still be drawn"


def test_optional_labels_are_genuinely_optional():
    bare = svg(range_label="", height_label="")
    assert "<polyline" in bare and len(bare) < len(svg())


# ── input guards ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("angle", [0, 4, 86, 90, 120, -30])
def test_an_angle_with_no_visible_arc_is_refused(angle):
    # Only for the ANGLED scene. A flat or vertical launch renders as a line or
    # a spike; better to raise and let _materialise_template drop the event
    # than to draw nonsense.
    with pytest.raises(ValueError):
        svg(angle_deg=angle, show_dropped_ball=False)


def test_the_angle_is_ignored_for_the_dropped_ball_scene():
    """It is a horizontal launch by construction, so an angle cannot apply.

    Accepting one and quietly ignoring it beats raising: the model fills these
    params, and refusing a plausible-looking call would drop the diagram
    entirely for a parameter that does not change the picture.
    """
    assert svg(angle_deg=45, show_dropped_ball=True) == svg(angle_deg=10, show_dropped_ball=True)


@pytest.mark.parametrize("angle", [5, 15, 45, 60, 85])
def test_every_usable_angle_renders(angle):
    out = svg(angle_deg=angle)
    assert out.startswith("<svg") and len(out) > 500


# ── routing ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("concept", [
    "Projectile Motion",
    "Projectile Motion: Range, Height and Time of Flight",
    "A ball is fired horizontally from a cliff",
    "Time of flight and maximum height",
])
def test_projectile_content_now_gets_the_scene(concept):
    assert suggest_diagram_template(concept, "", "") == "projectile_scene"


@pytest.mark.parametrize("concept,expected", [
    ("Resolving a force into components", "vector_resolution"),
    ("Vector Addition and Subtraction", "vector_resolution"),
    ("Friction on an inclined plane", "free_body_diagram"),
])
def test_the_new_cue_did_not_steal_from_the_old_ones(concept, expected):
    """Scene cues are checked FIRST, so a too-greedy pattern would silently
    capture content that was correctly routed before."""
    assert suggest_diagram_template(concept, "", "") == expected
