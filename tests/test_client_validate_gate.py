"""The server refuses what the client would refuse — one validator, not two.

`sanitize_widget_payload` used to be the whole gate, and it measured the
server's idea of a valid payload: a registered widget id, a params dict, a
label budget. It did not know that `reaction_scheme` caps a species label at
10 characters, or that `data_table_trend` wants ONE FLAT array rather than an
array of rows, because those rules live in the client's `validate()` and
nothing here ever asked it.

Measured before this gate existed: 50 of 123 stored payloads across four
subjects would not draw, including 14 of 14 `data_table_trend` — a widget that
had never rendered once, anywhere, while every one of its payloads passed this
function.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.drona.widget_registry import sanitize_widget_payload  # noqa: E402


def _scheme(species):
    return {
        "widget": "reaction_scheme",
        "version": 1,
        "params": {
            "caption": "acid to acyl chloride",
            "species": species,
            "step_from": [0], "step_to": [1],
            "step_reagent": ["SOCl2"], "step_kind": ["major"],
            "step_progress": 1, "highlight_step": -1,
        },
    }


def test_a_twenty_one_character_species_label_is_refused_at_the_server():
    # This probed 14 characters until 2026-09-12, when Raasikh raised the caps
    # to 20/20. A 14-char name in a TWO-species scheme now genuinely fits, so
    # the old assertion was asserting a rule that no longer exists; it is moved
    # to the boundary rather than deleted, because the claim being made --
    # the server refuses what the client refuses -- is unchanged.
    over = _scheme(["RCOOH", "twentyonecharacters!!"])
    assert len(over["params"]["species"][1]) == 21
    assert sanitize_widget_payload(over) is None


def test_a_label_within_the_cap_that_still_does_not_FIT_is_refused():
    # The cap is a pre-filter; WIDTH is the real gate. Three 20-char species
    # break no cap and still cannot be drawn at 343x236, which is why raising
    # the cap from 10 to 20 moved only two of the corpus's stored payloads.
    # Without this test the suite would record the cap as the whole rule.
    wide = {
        "widget": "reaction_scheme", "version": 1,
        "params": {
            "caption": "three wide species",
            "species": ["CH3CH2CH2CH2CH2CH2CH", "CH3CH2CH2CH2CH2CH2Br",
                        "CH3CH2CH2CH2CH2CH2OH"],
            "step_from": [0, 1], "step_to": [1, 2],
            "step_reagent": ["Br2", "KOH"], "step_kind": ["major", "major"],
            "step_progress": 1, "highlight_step": -1,
        },
    }
    assert all(len(sp) <= 20 for sp in wide["params"]["species"])
    sink: dict = {}
    assert sanitize_widget_payload(wide, reason_sink=sink) is None
    # And the refusal carries a MEASUREMENT, which is what makes the planner's
    # one repair attempt worth making.
    assert "pt" in sink["why"], sink


def test_the_same_payload_within_the_cap_is_accepted():
    # The control. Without it, a gate that refused EVERYTHING would pass the
    # test above — the check-that-passes-on-absent-information shape.
    ok = sanitize_widget_payload(_scheme(["RCOOH", "RCOCl"]))
    assert ok is not None
    assert ok["payload"]["widget"] == "reaction_scheme"
    assert ok["payload"]["params"]["species"] == ["RCOOH", "RCOCl"]


def test_data_table_trend_nested_rows_are_refused():
    # The shape every model emitted and the client never accepted: an array of
    # rows where a flat row-major array is wanted.
    nested = {
        "widget": "data_table_trend", "version": 1,
        "params": {
            "cell_kind": "numeric",
            "row_labels": ["Radio", "Microwave", "Infrared"],
            "col_labels": ["f (Hz)", "lambda (m)"],
            "values": [[1e8, 3.0], [1e10, 0.03], [1e13, 3e-5]],
            "trend_col": 0, "highlight_row": -1, "unit": "", "caption": "bands",
        },
    }
    assert sanitize_widget_payload(nested) is None

    flat = dict(nested)
    flat["params"] = dict(nested["params"], values=[1e8, 3.0, 1e10, 0.03, 1e13, 3e-5])
    assert sanitize_widget_payload(flat) is not None
