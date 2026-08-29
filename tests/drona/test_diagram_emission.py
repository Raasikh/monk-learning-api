"""The live path from a model-chosen template to a board event the client draws.

The tutor does not author SVG — it names a template and fills its labels, and
the server renders. Rendering is local string building (~0.1ms), so a diagram
rides the same WS frame as the rest of the board instead of costing a round
trip. These pin the contract that makes that safe: every template must render
well inside the sanitizer's size cap, and bad model output must be refused
rather than crash a lesson.
"""

import pytest

from app.drona.diagram_templates import TEMPLATES, render

# tutor.py drops any diagram event whose svg exceeds this, so a template that
# outgrew it would vanish silently from the board.
SANITIZER_SVG_CAP = 20000

# One realistic call per template, using the shapes prompts/tutor.md documents.
REALISTIC = {
    "free_body_diagram": dict(
        body_label="block",
        forces=[{"label": "mg", "angle": 270}, {"label": "N", "angle": 120}, {"label": "f", "angle": 30}],
    ),
    "vector_resolution": dict(magnitude_label="50 N", angle_deg=37, x_label="Fx", y_label="Fy"),
    "ray_diagram": dict(optic_type="convex_lens", object_pos=4.0, focal_length=1.0),
    "circuit_diagram": dict(components=[{"type": "battery", "label": "V"}, {"type": "resistor", "label": "R"}]),
    "labeled_axes_plot": dict(
        x_label="V", y_label="P",
        curve_points=[[i / 5, 1 / (i / 5 + 0.2)] for i in range(1, 16)],
        annotations=[], title="Isotherm",
    ),
    "comparison_table": dict(
        headers=["Property", "Ideal", "Real"],
        rows=[["Volume", "negligible", "finite"], ["Forces", "none", "present"]],
        title="Ideal vs Real",
    ),
    "boxed_derivation": dict(steps=["v = u + at", "s = ut + at^2/2"], title="Kinematics"),
    "process_flow": dict(stages=["Glycolysis", "Krebs", "ETC"], title="Respiration"),
}


# The comparison scene, not the plain arc — it is the case the template exists
# for and the one whose geometry is easiest to get wrong.
REALISTIC["projectile_scene"] = {
    "launch_label": "u = 20 m/s",
    "range_label": "R",
    "height_label": "",
    "show_dropped_ball": True,
    "ground_label": "both land together",
}


def test_every_template_has_a_realistic_case_here():
    # A new template with no coverage would ship unexercised.
    assert set(REALISTIC) == set(TEMPLATES)


@pytest.mark.parametrize("name", sorted(REALISTIC))
def test_template_renders_within_the_sanitizer_cap(name):
    svg = render(name, **REALISTIC[name])
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert len(svg) < SANITIZER_SVG_CAP, f"{name} would be dropped for size"


@pytest.mark.parametrize("name", sorted(REALISTIC))
def test_rendered_svg_carries_no_script_or_handlers(name):
    # The client sanitizes again, but nothing should rely on that.
    svg = render(name, **REALISTIC[name]).lower()
    assert "<script" not in svg
    assert "javascript:" not in svg
    assert " onclick" not in svg and " onload" not in svg


def test_unknown_template_is_refused_not_crashed():
    # A hallucinated template name must raise something the caller can catch
    # and drop, never take the turn down.
    with pytest.raises(ValueError) as err:
        render("holographic_projection", foo=1)
    assert "unknown diagram template" in str(err.value)


def test_missing_and_wrong_params_are_refused():
    with pytest.raises(ValueError):
        render("ray_diagram", optic_type="convex_lens")          # missing args
    with pytest.raises(ValueError):
        render("ray_diagram", optic_type="banana", object_pos=4.0, focal_length=1.0)


def test_object_at_the_focus_is_refused_rather_than_drawn_wrong():
    # The image runs to infinity; no honest fixed-canvas drawing exists.
    with pytest.raises(ValueError):
        render("ray_diagram", optic_type="convex_lens", object_pos=1.0, focal_length=1.0)
