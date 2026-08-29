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
