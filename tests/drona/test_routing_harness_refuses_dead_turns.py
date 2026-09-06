"""The routing harness must refuse to summarise a run containing dead turns.

This is a test about the INSTRUMENT, not the product, and it exists because
the instrument already lied once. `measure_widget_routing` wrapped
`sanitize_widget_payload` with a fixed signature; the routing work added an
`archetype_widget` kwarg; every archetype-branch call then raised TypeError,
which `process_tutor_turn_stream` catches as "Error during LLM turn". 33 of
40 turns produced no board events and the run reported `fired 0/70`.

That number was reported upward as a live product regression -- five biology
concepts supposedly teaching with a blank board -- when the truth was that
those turns never reached the model at all. `llm_ok` was False in every one
of those records the whole time.

A turn that did not run is not a zero. It is an absence, and a rate computed
over absences is a fiction.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "measure_widget_routing.py"


def _load():
    spec = importlib.util.spec_from_file_location("measure_widget_routing", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["measure_widget_routing"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write(tmp_path: Path, rows) -> str:
    p = tmp_path / "rows.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return str(p)


def _row(**kw):
    base = {"subtopic_key": "a-concept", "segment_index": 1, "llm_ok": True,
            "turn_error": None, "harness_error": None, "fired": False}
    base.update(kw)
    return base


def test_a_clean_run_is_allowed_to_summarise(tmp_path):
    mod = _load()
    mod.assert_every_turn_ran(_write(tmp_path, [_row(), _row(segment_index=2)]))


def test_one_dead_turn_stops_the_summary(tmp_path, capsys):
    """The exact shape that fooled us: ONE failed turn among healthy ones."""
    mod = _load()
    rows = [_row(), _row(segment_index=2),
            _row(segment_index=3, llm_ok=False,
                 turn_error={"message": "Something went wrong — retrying turn"})]
    with pytest.raises(SystemExit) as exc:
        mod.assert_every_turn_ran(_write(tmp_path, rows))
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "TURNS DID NOT RUN" in out
    assert "cannot be summarised" in out.replace("\n", " ")
    # It must name the failure, not just count it -- the generic message is
    # what made this invisible, so the harness points at the run log.
    assert "Something went wrong" in out
    assert "Error during LLM turn" in out


def test_it_does_not_pass_vacuously_on_an_empty_run(tmp_path):
    """No records is not a clean run.

    A guard whose input silently empties passes forever. This codebase has
    shipped that shape more than once.
    """
    mod = _load()
    mod.assert_every_turn_ran(_write(tmp_path, [_row()]))  # sanity: 1 row is fine
    with pytest.raises(AssertionError):
        rows = [json.loads(l) for l in open(_write(tmp_path, []), encoding="utf-8")]
        assert rows, "zero records means the harness measured nothing"
