"""Contract tests for app.drona.diagram_templates.

These guard the invariants PremiumBoardEvent.tsx depends on: parseable static
SVG, an explicit viewBox, no script/event handlers, a size budget, and only the
source colours restyleSvgString knows how to remap.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from app.drona import diagram_templates as dt

# --------------------------------------------------------------------------
# realistic JEE/NEET payloads, one per template
# --------------------------------------------------------------------------

SAMPLES: dict[str, dict] = {
    "free_body_diagram": {
        "body_label": "block m",
        "forces": [
            {"label": "N", "angle": 60},
            {"label": "mg", "angle": 270},
            {"label": "f (friction)", "angle": 150, "length": 0.7},
            {"label": "mg sin θ", "angle": 330, "length": 0.8},
        ],
    },
    "comparison_table": {
        "headers": ["Property", "Ideal gas", "Real gas"],
        "rows": [
            ["Intermolecular force", "Zero", "Present, non-zero"],
            ["Equation", "PV = nRT", "van der Waals"],
            ["Compressibility Z", "Z = 1 always", "Z ≠ 1 in general"],
        ],
        "title": "Ideal vs Real Gases",
    },
    "boxed_derivation": {
        "steps": [
            "v² = u² + 2as, with u = 0",
            "a = g sin θ − μ g cos θ",
            "v² = 2 g L (sin θ − μ cos θ)",
            "v = √(2 g L (sin θ − μ cos θ))",
        ],
        "title": "Speed at the foot of an incline",
    },
    "labeled_axes_plot": {
        "x_label": "displacement x (m)",
        "y_label": "PE U(x) (J)",
        "curve_points": [(i * 0.5, (i * 0.5 - 3) ** 2 - 4) for i in range(13)],
        "annotations": [
            {"x": 3.0, "y": -4.0, "text": "stable equilibrium"},
            {"x": 6.0, "y": 5.0, "text": "turning point"},
        ],
        "title": "Potential energy well",
    },
    "ray_diagram": {
        "optic_type": "convex_lens",
        "object_pos": 30.0,
        "focal_length": 10.0,
    },
    "circuit_diagram": {
        "components": [
            {"type": "battery", "label": "12 V"},
            {"type": "resistor", "label": "R₁ = 4Ω"},
            {"type": "ammeter", "label": "A"},
            {"type": "bulb", "label": "lamp"},
            {"type": "switch", "label": "K"},
        ],
    },
    "vector_resolution": {
        "magnitude_label": "F = 50 N",
        "angle_deg": 37,
        "x_label": "F cos 37°",
        "y_label": "F sin 37°",
    },
    "process_flow": {
        "stages": [
            "Glycolysis (cytosol)",
            "Link reaction",
            "Krebs cycle",
            "Electron transport chain",
            "ATP synthase",
        ],
        "title": "Aerobic respiration",
    },
}

ALL_NAMES = sorted(dt.TEMPLATES)

BAD_INPUTS: dict[str, list[dict]] = {
    "free_body_diagram": [
        {"body_label": "", "forces": [("N", 90)]},
        {"body_label": "block", "forces": []},
        {"body_label": "block", "forces": [("N", "up")]},
        {"body_label": "block", "forces": [{"label": "N"}]},
        {"body_label": 42, "forces": [("N", 90)]},
        {"body_label": "block", "forces": "N"},
    ],
    "comparison_table": [
        {"headers": ["only one"], "rows": [["a"]]},
        {"headers": ["a", "b", "c", "d"], "rows": [["1", "2", "3", "4"]]},
        {"headers": ["a", "b"], "rows": []},
        {"headers": ["a", "b"], "rows": [["only one cell"]]},
        {"headers": ["a", "b"], "rows": [[None, "x"]]},
    ],
    "boxed_derivation": [
        {"steps": ["single step"]},
        {"steps": []},
        {"steps": ["a", 7]},
        {"steps": ["a", "b"], "title": 3},
    ],
    "labeled_axes_plot": [
        {"x_label": "t", "y_label": "v", "curve_points": [(0, 0)]},
        {"x_label": "", "y_label": "v", "curve_points": [(0, 0), (1, 1)]},
        {"x_label": "t", "y_label": "v", "curve_points": [(0, 0), (1, "x")]},
        {"x_label": "t", "y_label": "v", "curve_points": [(0, 0), (1,)]},
        {
            "x_label": "t",
            "y_label": "v",
            "curve_points": [(0, 0), (1, 1)],
            "annotations": [{"x": 1}],
        },
        {
            "x_label": "t",
            "y_label": "v",
            "curve_points": [(0, 0), (float("inf"), 1)],
        },
    ],
    "ray_diagram": [
        {"optic_type": "banana_lens", "object_pos": 30, "focal_length": 10},
        {"optic_type": "convex_lens", "object_pos": -30, "focal_length": 10},
        {"optic_type": "convex_lens", "object_pos": 30, "focal_length": 0},
        {"optic_type": "convex_lens", "object_pos": 10.5, "focal_length": 10},
        {"optic_type": "convex_lens", "object_pos": "far", "focal_length": 10},
    ],
    "circuit_diagram": [
        {"components": [{"type": "resistor"}]},
        {"components": [{"type": "flux capacitor"}, {"type": "resistor"}]},
        {"components": []},
        {"components": [{"type": "resistor"}] * 9},
        {"components": [{"type": "resistor", "label": 5}, {"type": "cell"}]},
    ],
    "vector_resolution": [
        {"magnitude_label": "F", "angle_deg": 90, "x_label": "Fx", "y_label": "Fy"},
        {"magnitude_label": "F", "angle_deg": 0, "x_label": "Fx", "y_label": "Fy"},
        {"magnitude_label": "", "angle_deg": 30, "x_label": "Fx", "y_label": "Fy"},
        {"magnitude_label": "F", "angle_deg": 5000, "x_label": "Fx", "y_label": "Fy"},
        {"magnitude_label": "F", "angle_deg": None, "x_label": "Fx", "y_label": "Fy"},
    ],
    "process_flow": [
        {"stages": ["only one"]},
        {"stages": []},
        {"stages": ["a"] * 9},
        {"stages": ["a", None]},
        {"stages": "abc"},
    ],
}

HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}")
ON_ATTR_RE = re.compile(r"\son[a-zA-Z]+\s*=", re.IGNORECASE)


def _render(name: str) -> str:
    return dt.render(name, **SAMPLES[name])


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------


def test_registry_covers_all_eight_templates():
    assert len(dt.TEMPLATES) == 8
    assert set(dt.TEMPLATES) == set(SAMPLES)
    assert set(dt.TEMPLATES) == set(BAD_INPUTS)


def test_render_rejects_unknown_name():
    with pytest.raises(ValueError) as exc:
        dt.render("holographic_manifold")
    assert "unknown diagram template" in str(exc.value)
    # the message should point the caller at what does exist
    assert "free_body_diagram" in str(exc.value)


def test_render_rejects_non_string_name():
    with pytest.raises(ValueError):
        dt.render(None)  # type: ignore[arg-type]


def test_render_wraps_bad_kwargs_as_value_error():
    with pytest.raises(ValueError) as exc:
        dt.render("process_flow", not_a_real_kwarg=1)
    assert "bad arguments" in str(exc.value)


# --------------------------------------------------------------------------
# per-template contract
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ALL_NAMES)
def test_returns_non_empty_string(name):
    svg = _render(name)
    assert isinstance(svg, str)
    assert svg.strip()


@pytest.mark.parametrize("name", ALL_NAMES)
def test_parses_as_xml(name):
    root = ET.fromstring(_render(name))
    assert root.tag.endswith("svg")


@pytest.mark.parametrize("name", ALL_NAMES)
def test_has_explicit_viewbox(name):
    root = ET.fromstring(_render(name))
    view_box = root.get("viewBox")
    assert view_box, f"{name} emitted no viewBox"
    nums = view_box.split()
    assert len(nums) == 4
    assert float(nums[2]) > 0 and float(nums[3]) > 0


@pytest.mark.parametrize("name", ALL_NAMES)
def test_no_script_and_no_event_handlers(name):
    svg = _render(name)
    assert "<script" not in svg.lower()
    assert "javascript:" not in svg.lower()
    assert not ON_ATTR_RE.search(svg), f"{name} emitted an on* attribute"
    for banned in (
        "<image", "<foreignobject", "<iframe", "<use", "<defs", "<marker",
        "xlink:href", "href=", "url(", "@import", "data:",
    ):
        assert banned not in svg.lower(), f"{name} emitted a banned construct: {banned}"
    # the only URL anywhere may be the SVG namespace declaration
    assert svg.lower().count("http") == 1
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg


@pytest.mark.parametrize("name", ALL_NAMES)
def test_under_size_budget(name):
    svg = _render(name)
    assert len(svg) < dt.MAX_SVG_CHARS, f"{name} is {len(svg)} chars"


@pytest.mark.parametrize("name", ALL_NAMES)
def test_only_uses_allowed_source_colors(name):
    svg = _render(name)
    used = {h.lower() for h in HEX_RE.findall(svg)}
    assert used, f"{name} emitted no colours at all"
    stray = used - dt.ALLOWED_COLORS
    assert not stray, f"{name} uses colours restyleSvgString cannot remap: {stray}"


@pytest.mark.parametrize("name", ALL_NAMES)
def test_sets_no_font_family(name):
    # restyleSvgString rewrites font-family anyway; emitting one is dead weight
    assert "font-family" not in _render(name)


@pytest.mark.parametrize("name", ALL_NAMES)
def test_uses_only_animatable_primitives(name):
    """Every drawn element must be something getTotalLength() understands."""
    allowed = {
        "svg", "path", "line", "polyline", "polygon", "circle", "ellipse",
        "rect", "text", "g",
    }
    root = ET.fromstring(_render(name))
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        assert tag in allowed, f"{name} emitted a non-drawable <{tag}>"


@pytest.mark.parametrize("name", ALL_NAMES)
def test_has_at_least_one_stroked_shape(name):
    """A diagram with nothing to draw would animate as an empty box."""
    root = ET.fromstring(_render(name))
    stroked = [
        el for el in root.iter()
        if el.get("stroke") not in (None, "none", "transparent")
    ]
    assert len(stroked) >= 2, f"{name} has almost nothing to animate"


@pytest.mark.parametrize("name", ALL_NAMES)
def test_bad_input_raises_value_error(name):
    for kwargs in BAD_INPUTS[name]:
        with pytest.raises(ValueError):
            dt.TEMPLATES[name](**kwargs)


# --------------------------------------------------------------------------
# escaping — labels come from an LLM
# --------------------------------------------------------------------------

# Short enough to survive every template's label cap, so the assertions below
# are testing escaping rather than truncation.
HOSTILE = "&<script>"


@pytest.mark.parametrize(
    "name,kwargs",
    [
        ("free_body_diagram", {"body_label": HOSTILE, "forces": [(HOSTILE, 45)]}),
        (
            "comparison_table",
            {"headers": [HOSTILE, "b"], "rows": [[HOSTILE, "x"]], "title": HOSTILE},
        ),
        ("boxed_derivation", {"steps": [HOSTILE, HOSTILE], "title": HOSTILE}),
        (
            "labeled_axes_plot",
            {
                "x_label": HOSTILE,
                "y_label": HOSTILE,
                "curve_points": [(0, 0), (1, 1)],
                "annotations": [{"x": 1, "y": 1, "text": HOSTILE}],
                "title": HOSTILE,
            },
        ),
        (
            "circuit_diagram",
            {"components": [("resistor", HOSTILE), ("cell", HOSTILE)]},
        ),
        (
            "vector_resolution",
            {
                "magnitude_label": HOSTILE,
                "angle_deg": 40,
                "x_label": HOSTILE,
                "y_label": HOSTILE,
            },
        ),
        ("process_flow", {"stages": [HOSTILE, HOSTILE], "title": HOSTILE}),
    ],
)
def test_hostile_labels_are_escaped(name, kwargs):
    svg = dt.TEMPLATES[name](**kwargs)
    # still a well-formed, script-free document
    ET.fromstring(svg)
    assert "<script" not in svg.lower()
    assert not ON_ATTR_RE.search(svg)
    # the literal markup never survives; its escaped form does
    assert "&lt;script&gt;" in svg
    # a bare ampersand would break XML parsing outright
    assert "&amp;" in svg
    assert not re.search(r"&(?!amp;|lt;|gt;|quot;|#x27;|#\d+;)", svg)


def test_escaped_text_round_trips_to_the_original_characters():
    svg = dt.process_flow(["<b>bold</b> & bolder", "second"])
    root = ET.fromstring(svg)
    texts = " ".join(t.text or "" for t in root.iter() if t.tag.endswith("text"))
    assert "<b>" in texts and "&" in texts


# --------------------------------------------------------------------------
# overflow handling
# --------------------------------------------------------------------------


def test_long_labels_are_truncated_not_overflowed():
    long_label = "supercalifragilistic " * 40
    svg = dt.free_body_diagram(long_label, [(long_label, 90)])
    root = ET.fromstring(svg)
    for t in root.iter():
        if t.tag.endswith("text"):
            assert len(t.text or "") <= 24, "label was not capped"
    assert len(svg) < dt.MAX_SVG_CHARS


def test_max_sized_table_stays_within_budget():
    svg = dt.comparison_table(
        headers=["A fairly long header", "Another long header", "Third one here"],
        rows=[["x" * 62, "y" * 62, "z" * 62] for _ in range(7)],
        title="A" * 60,
    )
    assert len(svg) < dt.MAX_SVG_CHARS
    ET.fromstring(svg)


def test_max_sized_process_flow_stays_within_budget():
    svg = dt.process_flow(["A long stage name here" for _ in range(8)], title="Big flow")
    assert len(svg) < dt.MAX_SVG_CHARS
    ET.fromstring(svg)


# --------------------------------------------------------------------------
# template-specific behaviour worth pinning
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "optic,obj,f,expect_real",
    [
        ("convex_lens", 30.0, 10.0, True),      # beyond 2F: real, inverted
        ("convex_lens", 6.0, 10.0, False),      # inside F: magnifying glass
        ("concave_lens", 20.0, 10.0, False),    # always virtual
        ("concave_mirror", 40.0, 15.0, True),   # beyond C: real
        ("concave_mirror", 5.0, 15.0, False),   # inside F: virtual, erect
        ("convex_mirror", 25.0, 12.0, False),   # always virtual
    ],
)
def test_ray_diagram_all_optics(optic, obj, f, expect_real):
    svg = dt.ray_diagram(optic, obj, f)
    ET.fromstring(svg)
    assert len(svg) < dt.MAX_SVG_CHARS
    assert ("real" in svg) is expect_real
    assert ("virtual" in svg) is not expect_real
    if not expect_real:
        # virtual constructions must show dashed back-extensions
        assert "stroke-dasharray" in svg


def test_ray_diagram_rejects_image_at_infinity():
    with pytest.raises(ValueError) as exc:
        dt.ray_diagram("convex_lens", 10.0, 10.0)
    assert "infinity" in str(exc.value)


@pytest.mark.parametrize("ctype", dt._COMPONENT_TYPES)
def test_circuit_renders_every_component_type(ctype):
    svg = dt.circuit_diagram([{"type": ctype, "label": ctype}, {"type": "resistor"}])
    ET.fromstring(svg)
    assert len(svg) < dt.MAX_SVG_CHARS


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6])
def test_circuit_loop_scales_with_component_count(n):
    svg = dt.circuit_diagram([{"type": "resistor", "label": f"R{i}"} for i in range(n)])
    ET.fromstring(svg)


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6, 7, 8])
def test_process_flow_layouts(n):
    svg = dt.process_flow([f"Stage {i}" for i in range(n)])
    ET.fromstring(svg)
    assert len(svg) < dt.MAX_SVG_CHARS


@pytest.mark.parametrize("angle", [15, 37, 120, 200, 315, -50])
def test_vector_resolution_all_quadrants(angle):
    svg = dt.vector_resolution("v", angle, "vx", "vy")
    ET.fromstring(svg)


def test_plot_handles_flat_curve_without_dividing_by_zero():
    svg = dt.labeled_axes_plot("t", "v", [(0, 5), (1, 5), (2, 5)])
    ET.fromstring(svg)


def test_free_body_diagram_accepts_mapping_and_tuple_forms():
    a = dt.free_body_diagram("m", [{"label": "N", "angle": 90}])
    b = dt.free_body_diagram("m", [("N", 90)])
    assert a == b


def test_boxed_derivation_boxes_the_final_step():
    svg = dt.boxed_derivation(["step one", "final answer"])
    root = ET.fromstring(svg)
    boxed = [
        el for el in root.iter()
        if el.tag.endswith("rect") and el.get("stroke") == dt.PRIMARY
    ]
    assert len(boxed) == 1, "exactly the final step should be boxed"
