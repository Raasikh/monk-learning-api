"""Snap-path model calls are billed to a student; planner calls are not.

This exists because the gap it closes was invisible for the life of the
feature. `llm_calls.user_id` has been a column since migration 0018 and the
snap path never wrote it — 95% of rows carried NULL — so /admin's per-user cost
could only see the 5% that came from the tutor. Nothing failed. There was no
error, no warning, and the dashboard reported a confident wrong number.

A static check rather than only a behavioural one, because the failure mode is
someone adding a seventh `snap_*` service next year and forgetting the keyword.
No test that exercises today's six calls would catch that; this one does.

The second half is the more interesting assertion: the planner must NOT
attribute. `segment` / `outline` / `widget_payload` author a lesson once into
`lesson_plans` and replay it to every student who takes it. Billing that to
whoever triggered generation would make one student look enormously expensive
for a cost that is genuinely shared, and would corrupt the per-user figure in
the opposite direction. That is a deliberate decision, so it is pinned too —
otherwise the next person to read this file "fixes" it.
"""

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


def _record_call_sites(relpath):
    """(line, passes_user_id) for every record_call/record_call_bg in a file."""
    path = REPO / relpath
    tree = ast.parse(path.read_text(), str(path))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = (node.func.id if isinstance(node.func, ast.Name)
                else node.func.attr if isinstance(node.func, ast.Attribute) else None)
        if name in ("record_call", "record_call_bg"):
            out.append((node.lineno, any(k.arg == "user_id" for k in node.keywords)))
    return out


def test_every_snap_model_call_is_billed_to_a_student():
    sites = _record_call_sites("app/snap.py")
    assert sites, "no record_call sites found in app/snap.py — did the file move?"
    unattributed = [ln for ln, has in sites if not has]
    assert not unattributed, (
        f"app/snap.py lines {unattributed} record a model call without user_id. "
        "Every snap_* service is per-student — one photo, one person — so its "
        "cost must be attributable. Thread user_id down from the router; "
        "_call_with_one_retry and _streamed_solve both accept it."
    )


def test_the_planner_deliberately_does_not_attribute():
    sites = _record_call_sites("app/drona/planner.py")
    assert sites, "no record_call sites found in app/drona/planner.py"
    attributed = [ln for ln, has in sites if has]
    assert not attributed, (
        f"app/drona/planner.py lines {attributed} now pass user_id. Lesson "
        "authoring is cached in lesson_plans and replayed to everyone who takes "
        "the lesson, so billing it to the student who happened to trigger "
        "generation is wrong. It belongs in the 'content' bucket "
        "(migration 0051), which is deliberately unattributed."
    )


SNAP_ENTRY_POINTS = [
    "solve_snapped_image", "iter_snapped_questions", "solve_question",
    "transcribe_questions", "describe_diagram", "describe_option_figures",
    "match_answer_to_options", "_call_with_one_retry", "_streamed_solve",
]


@pytest.mark.parametrize("fname", SNAP_ENTRY_POINTS)
def test_snap_entry_points_accept_user_id_keyword_only(fname):
    """Keyword-only and defaulted.

    Keyword-only so it can never be supplied positionally by accident into a
    signature that already carries several optional strings; defaulted so a
    script or a test with no user behaves exactly as before rather than
    breaking.
    """
    tree = ast.parse((REPO / "app/snap.py").read_text())
    fn = next((n for n in tree.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fname), None)
    assert fn is not None, f"{fname}() not found in app/snap.py"
    kwonly = [a.arg for a in fn.args.kwonlyargs]
    assert "user_id" in kwonly, f"{fname}() must take user_id as keyword-only"
    assert "user_id" not in [a.arg for a in fn.args.args], \
        f"{fname}() takes user_id positionally; it must be keyword-only"
    idx = kwonly.index("user_id")
    assert fn.args.kw_defaults[idx] is not None, \
        f"{fname}()'s user_id must default to None so callers without one still work"


def test_the_id_actually_reaches_the_row(monkeypatch):
    """Behavioural companion to the static checks: it is really written."""
    import app.snap as snap

    seen = []
    monkeypatch.setattr(snap, "record_call", lambda *a, **k: seen.append(k))

    class _Res:
        choices = [type("C", (), {"message": type("M", (), {"content": '{"ok": true}'})()})()]
        usage = None
        error = None

    snap._call_with_one_retry("transcribe", lambda *_a, **_k: _Res(), "d=abc",
                              service="snap_transcribe", user_id="user-42")

    assert seen, "record_call was never reached"
    assert all(k.get("user_id") == "user-42" for k in seen), \
        f"user_id did not reach llm_calls: {[k.get('user_id') for k in seen]}"


def test_no_user_still_records_the_call():
    """A script or backfill has no student. The call must still be booked —
    as NULL, never dropped. Unrecorded spend is the failure this whole module
    of accounting exists to prevent."""
    tree = ast.parse((REPO / "app/snap.py").read_text())
    fn = next(n for n in tree.body
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_call_with_one_retry")
    idx = [a.arg for a in fn.args.kwonlyargs].index("user_id")
    default = fn.args.kw_defaults[idx]
    assert isinstance(default, ast.Constant) and default.value is None
