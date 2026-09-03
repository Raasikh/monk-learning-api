"""Which client-rendered WIDGET a turn's own content calls for, if any.

Separate from test_diagram_cues.py on purpose: suggest_widget/_WIDGET_CUES is
a second, independent table from suggest_diagram_template/_DIAGRAM_CUES —
field_lines has no server-side SVG template (diagram_templates.TEMPLATES),
so it cannot live in the table test_every_suggested_template_actually_exists
checks against. See _WIDGET_CUES' own comment in tutor.py.
"""

import pytest

from app.drona.tutor import _DIAGRAM_CUES, _WIDGET_CUES, suggest_widget


@pytest.mark.parametrize("concept,expected", [
    ("Electric Field Lines", "field_lines"),
    ("Electric Field due to a Point Charge", "field_lines"),
    ("Field Lines Around a Dipole", "field_lines"),
    ("Neutral Point Between Two Charges", "field_lines"),
    ("Field Between Parallel Plates", "field_lines"),
])
def test_bare_concept_names_pick_field_lines(concept, expected):
    assert suggest_widget(concept, "", "", "") == expected


@pytest.mark.parametrize("concept", [
    "Electric Charge: Properties, Quantisation and Charging",
    "Coulomb's Law and Electric Forces",
    "Adaptive Radiation",
    "Types of Sets: Empty, Finite, Infinite and Equal Sets",
])
def test_unrelated_concepts_get_no_suggestion(concept):
    assert suggest_widget(concept, "", "", "") is None


def test_widget_cue_empty_input_is_safe():
    assert suggest_widget("", "", "", "") is None
    assert suggest_widget() is None


def test_dipole_alone_stays_with_free_body_diagram():
    # "dipole" is already claimed by _DIAGRAM_CUES' free_body_diagram regex
    # (torque-on-a-dipole-in-a-field turns). suggest_widget is only ever
    # consulted when suggest_diagram_template found nothing (see tutor.py's
    # call site), so a bare "dipole" concept must not silently also match
    # here — if it did, whichever hint tutor.py checked second would never
    # fire, which is exactly the ambiguity this test is pinning down.
    import re
    assert not any(re.search(pattern, "electric dipole in external field")
                    for pattern, _ in _WIDGET_CUES)


def test_widget_cue_table_never_names_a_diagram_template():
    # field_lines is rendered by the student's app from parameters, not by
    # the server from a template name — it must never appear in
    # _DIAGRAM_CUES (test_every_suggested_template_actually_exists in
    # test_diagram_cues.py would fail the moment it did, since field_lines
    # is not and should not be registered in diagram_templates.TEMPLATES).
    diagram_template_names = {name for _, name in _DIAGRAM_CUES}
    widget_names = {name for _, name in _WIDGET_CUES}
    assert widget_names.isdisjoint(diagram_template_names)
