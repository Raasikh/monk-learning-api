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


def test_a_fourteen_character_species_label_is_refused_at_the_server():
    # The exact failure that cost chem12 ch8 its whole chapter: a species name
    # four characters over the client's cap, which the server happily stored.
    over = _scheme(["RCOOH", "fourteen-chars"])
    assert len(over["params"]["species"][1]) == 14
    assert sanitize_widget_payload(over) is None


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
