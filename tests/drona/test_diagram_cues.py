"""Which diagram template a turn's own content calls for.

The trigger table in prompts/tutor.md alone produced a diagram on about half
the turns that clearly wanted one — a real Trigonometry derivation and a real
dipole-forces turn both came back as pure text. A general rule the model has to
notice competes with the much louder "mirror every sentence on the board"
instruction beside it; naming the ONE template that fits THIS turn does not.
With the suggestion wired in, the same four subjects went 2/4 -> 4/4.

The cues run against the segment objective and teaching notes, which in
production are often just a concept name — so they must fire on bare names like
"Adaptive Radiation", not only on rich prose.
"""

import pytest

from app.drona.diagram_templates import TEMPLATES
from app.drona.tutor import suggest_diagram_template


@pytest.mark.parametrize("concept,expected", [
    ("Electric Dipole in External Field", "free_body_diagram"),
    ("Friction on an inclined plane", "free_body_diagram"),
    ("Resolving a force into components", "vector_resolution"),
    # Moved off vector_resolution deliberately. An arrow triangle is a correct
    # picture of the decomposition and nothing like the picture the content is
    # about — a launcher, an arc, and a ball dropped beside it.
    ("Projectile Motion", "projectile_scene"),
    ("Image formation by a convex lens", "ray_diagram"),
    ("Wheatstone Bridge", "circuit_diagram"),
    ("Series LCR Circuit: Impedance and Phase", "circuit_diagram"),
    ("Compound Angle Formulas and Trigonometric Identities", "boxed_derivation"),
    ("Adaptive Radiation", "process_flow"),
    ("Classification of Organic Compounds", "process_flow"),
])
def test_bare_concept_names_pick_the_right_template(concept, expected):
    # Bare names, no teaching notes — the hard case, and the one production
    # hits whenever a plan's notes are thin.
    assert suggest_diagram_template(concept, "", "") == expected


def test_comparison_beats_plot_for_vs():
    # "Ideal vs Real Gases" is a comparison, not a graph. A bare "vs" is far
    # more often shorthand for "compared with" than for a plotted axis pair,
    # so comparison_table is checked first.
    assert suggest_diagram_template("Ideal vs Real Gases", "", "") == "comparison_table"
    assert suggest_diagram_template("Mitosis vs Meiosis", "", "") == "comparison_table"
    # ...but a spelled-out "versus" between quantities is still a plot.
    assert suggest_diagram_template("Isotherms", "plot P versus V", "") == "labeled_axes_plot"


@pytest.mark.parametrize("concept", [
    "Electric Charge: Properties, Quantisation and Charging",
    "Ionization and Excitation Energy",
    "Economic Importance of Algae and Their Products",
    "Types of Sets: Empty, Finite, Infinite and Equal Sets",
])
def test_abstract_concepts_get_no_suggestion(concept):
    # Silence is the correct answer when no template genuinely fits. Suggesting
    # one anyway would push a picture onto content that has no geometry, and
    # the model would either force a bad fit or drop it.
    assert suggest_diagram_template(concept, "", "") is None


def test_every_suggested_template_actually_exists():
    # A cue pointing at a template name that is not registered would render
    # nothing and be silently dropped at materialise time.
    from app.drona.tutor import _DIAGRAM_CUES
    for _, name in _DIAGRAM_CUES:
        assert name in TEMPLATES, f"cue points at unknown template {name!r}"


def test_diagram_cue_empty_input_is_safe():
    assert suggest_diagram_template("", "", "") is None
    assert suggest_diagram_template() is None


# ── Worked-example offer ─────────────────────────────────────────────────────
# The rule is in prompts/tutor.md too, but four levels deep in the turn-depth
# structure, and the model skipped it on all three subjects tested. Naming the
# instruction for THIS turn is what fixed diagram selection; same technique.

from app.drona.tutor import turn_works_an_example


@pytest.mark.parametrize("objective,notes", [
    ("Solving projectile range numericals", "Work a numerical: u=20 m/s at 30 degrees, find range."),
    ("Calculating molarity", "Work an example: 5.85 g NaCl in 500 mL water."),
    ("Mole concept numericals", "Work an example: moles in 44 g CO2."),
    ("Dimensional Analysis", "Determine the dimensional formula of pressure."),
    ("Kirchhoff's Laws", "Compute the current in each branch."),
])
def test_numerical_turns_are_detected(objective, notes):
    assert turn_works_an_example(objective, notes, "") is True


@pytest.mark.parametrize("objective,notes", [
    ("Adaptive Radiation", "Darwin's finches diversified across islands."),
    ("Bryophytes: Liverworts and Mosses", "Structure and habitat."),
    ("Electric Field Lines", "Qualitative picture of field direction."),
])
def test_conceptual_turns_get_no_offer(objective, notes):
    # Offering to "pause and try it" on a turn with nothing to compute would be
    # noise, so silence is the correct answer here.
    assert turn_works_an_example(objective, notes, "") is False


def test_example_cue_empty_input_is_safe():
    assert turn_works_an_example("", "", "") is False
    assert turn_works_an_example() is False
