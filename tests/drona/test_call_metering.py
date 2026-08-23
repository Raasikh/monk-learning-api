"""Every Drona model call must land in `llm_calls`, with enough on the row to
say who spent it.

Two failures motivated this file, and both looked like working accounting:

1. The live paths — tutor turns and the two scoped doubt modes — never called
   record_call at all. They are by far the most frequent model calls in the
   product, so `llm_calls` held only question-bank and planner rows and a
   session's real cost could not be read back from the database.

2. The planner DID call record_call, and passed `chapter_id=chap_data.get("id")`
   — but chap_data came from `.select("name, subject")`, so the key was never
   present and every row ever written carried a null chapter. Wired-up-looking
   accounting that records nothing is worse than none, because nobody goes
   looking for it.

So these tests check the wiring structurally, not just that a call happens.
"""

import ast
import inspect
from pathlib import Path

import pytest

APP_DRONA = Path(__file__).resolve().parents[2] / "app" / "drona"

# Modules that make a live model call on a student's behalf. Each must meter.
# usage.py is the recorder itself; models.py only builds clients.
LIVE_CALL_MODULES = ["tutor.py", "scoped_turn.py", "planner.py"]


@pytest.mark.parametrize("module", LIVE_CALL_MODULES)
def test_every_model_calling_module_meters(module):
    src = (APP_DRONA / module).read_text()
    # The client call and the record must both be present. A module that gained
    # a chat.completions call without a record_call is the exact regression.
    assert "chat.completions.create" in src, f"{module} no longer calls the model — update this list"
    assert "record_call" in src, (
        f"{module} calls the model but never records it. Live spend recorded "
        f"nowhere is how 4,067 calls became unattributable."
    )


def test_live_student_paths_record_off_thread():
    # tutor and scoped_turn run inside a student's turn: a slow PostgREST insert
    # on the calling thread would delay speech. planner runs in a background
    # thread already, so the blocking form is correct there.
    for module in ("tutor.py", "scoped_turn.py"):
        src = (APP_DRONA / module).read_text()
        assert "record_call_bg(" in src, (
            f"{module} must use record_call_bg — the blocking form puts a "
            f"database round trip in front of the student's audio."
        )


def test_planner_selects_the_chapter_id_it_records():
    # The regression in full: reading `id` off a row that was never selected.
    src = (APP_DRONA / "planner.py").read_text()
    tree = ast.parse(src)

    selects = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "select"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ]
    chapter_selects = [s for s in selects if "subject" in s and "name" in s]
    assert chapter_selects, "no chapters select found — has the fetch moved?"
    for sel in chapter_selects:
        cols = {c.strip() for c in sel.split(",")}
        assert "id" in cols, (
            f"chapters select {sel!r} omits id, but record_call reads "
            f"chap_data['id'] — every planner row would record a null chapter."
        )


def test_segment_author_can_attribute_to_a_plan():
    # Segments 2..N are authored detached, after the plan row exists. Without
    # plan_id on those rows there is no way to total what one plan cost.
    from app.drona.planner import _author_segment

    params = inspect.signature(_author_segment).parameters
    assert "plan_id" in params, "_author_segment cannot attribute its spend to a plan"
    assert params["plan_id"].default is None, (
        "plan_id must be optional: segment 1 is authored before the plan row exists"
    )
