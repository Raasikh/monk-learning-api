"""Guardrails on the SVG validator.

validate() is the only thing standing between a model's output and a student's
board, so a bug in it is invisible in both directions: too strict and good
diagrams silently never appear, too loose and broken markup ships.
"""

from app.drona.diagram_author import validate



def test_entities_are_measured_as_glyphs_not_markup():
    """A label written as "&#215;" is one character wide, not six.

    _text_boxes reads the raw SVG string, so before this was fixed an entity
    inflated the estimated width by its markup length and the label "collided"
    with whatever sat to its right. Physics and chemistry figures use entities
    constantly — degree signs, multiplication crosses, <=, ± — so this rejected
    correct diagrams for a fault that did not exist.
    """
    from app.drona.diagram_author import _text_boxes

    entity = _text_boxes('<text x="0" y="20" font-size="17">&#215;</text>')
    literal = _text_boxes('<text x="0" y="20" font-size="17">×</text>')
    assert entity[0][2] == literal[0][2], "entity measured wider than the glyph"

    # and the whole-diagram consequence: two labels a comfortable gap apart
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 340 240">'
           '<rect x="0" y="0" width="340" height="240" fill="#ffffff"/>'
           '<line x1="10" y1="200" x2="330" y2="200" stroke="#1f2933"/>'
           '<text x="66" y="184" font-size="17" fill="#1f2933">&#215;</text>'
           '<text x="84" y="184" font-size="17" fill="#059669">[L T^-2]</text>'
           '</svg>')
    ok, reason = validate(svg)
    assert ok, reason


# ---------------------------------------------------------------------------
# The layout post-pass. Same stakes in both directions: a repair that does not
# satisfy the gate wastes a diagram, and a repair that satisfies the gate while
# making the picture worse ships a broken figure that nothing will catch again.
# ---------------------------------------------------------------------------

HEAD = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 260">'
BG = '<rect x="0" y="0" width="640" height="260" fill="#ffffff"/>'
DRAWN = '<line x1="20" y1="240" x2="620" y2="240" stroke="#1f2933" stroke-width="2"/>'


def _svg(*bits: str) -> str:
    return HEAD + BG + DRAWN + "".join(bits) + "</svg>"


def test_repair_clamps_a_label_back_inside_the_viewbox():
    from app.drona.diagram_author import repair_layout

    svg = _svg('<text x="600" y="100" font-size="16" fill="#1f2933">'
               'A label that runs off the right edge</text>')
    assert not validate(svg)[0]
    fixed, report = repair_layout(svg)
    assert validate(fixed)[0], validate(fixed)[1]
    assert report["strays_before"] == 1 and report["applied"]


def test_repair_separates_two_identical_labels():
    """overlaps() is TRUE for two identical boxes, so this is a real collision.

    It is also the degenerate case a naive nudge cannot solve: the overlap depth
    is the full box, and there is no side to pick from the geometry alone.
    """
    from app.drona.diagram_author import repair_layout

    label = '<text x="300" y="100" font-size="16" fill="#1f2933">Alpha</text>'
    svg = _svg(label, label)
    assert not validate(svg)[0]
    assert validate(repair_layout(svg)[0])[0]


def test_repair_nudges_on_the_minor_axis_not_the_major_one():
    """A label is wide and short, so it moves vertically.

    Sliding it horizontally would walk it away from the shape it names, which is
    a worse diagram that the gate would nonetheless pass.
    """
    from app.drona.diagram_author import _parse_texts, repair_layout

    svg = _svg('<text x="300" y="100" font-size="16" fill="#1f2933">Sodium ion</text>',
               '<text x="320" y="104" font-size="16" fill="#1f2933">Chloride ion</text>')
    fixed, _ = repair_layout(svg)
    before, after = _parse_texts(svg), _parse_texts(fixed)
    assert validate(fixed)[0]
    assert [t["x"] for t in before] == [t["x"] for t in after], "moved along x"
    assert [t["y"] for t in before] != [t["y"] for t in after], "did not move along y"


def test_repair_strips_font_family_unconditionally():
    from app.drona.diagram_author import repair_layout

    svg = _svg('<text x="200" y="100" font-size="16" font-family="Anek Latin" '
               'fill="#1f2933">Label</text>')
    assert not validate(svg)[0]
    fixed, report = repair_layout(svg)
    assert "font-family" not in fixed and report["font_family_stripped"]
    assert validate(fixed)[0]


def test_repair_returns_the_original_when_no_layout_can_work():
    """A label wider than the canvas can only be saved by redrawing.

    The rule that matters is the one about bailing: the post-pass must hand back
    something validate() still REJECTS, so the retry loop redraws it. Passing a
    half-nudged layout would spend the rejection and ship the bad figure.
    """
    from app.drona.diagram_author import repair_layout

    svg = _svg(f'<text x="10" y="100" font-size="17" fill="#1f2933">{"X" * 90}</text>')
    fixed, report = repair_layout(svg)
    assert fixed == svg, "must not half-repair an unsatisfiable layout"
    assert not validate(fixed)[0]
    assert report["unrepairable"] and not report["applied"]


def test_a_diagram_with_no_labels_is_its_own_category():
    """validate() PASSES an unlabelled diagram — nothing in the gate wants text.

    So "0 overlaps, 0 strays" on such a payload is not a clean layout, it is a
    figure that teaches nothing, and the report has to say which one it saw.
    """
    from app.drona.diagram_author import repair_layout

    svg = _svg()
    assert validate(svg)[0], "premise: the gate does not require labels"
    _, report = repair_layout(svg)
    assert report["no_labels"] and report["labels"] == 0


def test_repair_uses_the_render_gates_width_model_not_the_validators():
    """0.58 and no inset — verify-render.mjs textBox(), not _text_boxes().

    The validator's box (0.55 wide, inset by 0.12*size) is strictly contained in
    the render gate's, so repairing to the smaller one leaves labels the mobile
    gate still rejects. This pins the constant so a future edit cannot quietly
    swap in the looser model.
    """
    from app.drona.diagram_author import _GATE_CHAR_W, _gate_box, _text_boxes

    assert _GATE_CHAR_W == 0.58
    body, size = "Chloride ion", 16.0
    g = _gate_box(100.0, 100.0, size, "start", body)
    v = _text_boxes(f'<text x="100" y="100" font-size="{size:g}">{body}</text>')[0]
    assert g[0] <= v[0] and g[1] <= v[1] and g[2] >= v[2] and g[3] >= v[3], \
        "the repair box must contain the validator's box"
