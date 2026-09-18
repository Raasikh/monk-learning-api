"""I2 — a board change must not re-author the segments.

One hash over the whole of planner.py meant every widget-prompt tweak
invalidated every plan. Measured 2026-09-15: a three-line addition to a widget
prompt triggered a 29-chapter, 15-hour sweep — which rewrote the objectives,
which voided 72 of 86 human SANE judgements, because a verdict keyed to a
segment index follows the index onto whatever question replaces it.

The fifteen hours were not the expensive part. The review was.
"""
import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from app.drona import planner  # noqa: E402

PLANNER = REPO / "app/drona/planner.py"
REGISTRY = REPO / "app/drona/widget_registry.py"


def test_the_two_hashes_are_different_and_cover_the_whole_file():
    plan_src, board_src = planner._split_source()
    assert plan_src and board_src
    whole = PLANNER.read_text()
    # every byte of the file lands in exactly one side
    assert len(plan_src) + len(board_src) == len(whole)
    assert planner._plan_sha() != planner._board_sha()


def test_every_board_function_named_actually_exists():
    """A typo'd name would silently move that function into plan_sha, and the
    only symptom would be a prompt tweak costing a full sweep again."""
    tree = ast.parse(PLANNER.read_text())
    defined = {n.name for n in tree.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    missing = planner._BOARD_FUNCS - defined
    assert not missing, f"_BOARD_FUNCS names functions that do not exist: {missing}"


def test_editing_a_WIDGET_SPEC_moves_board_sha_and_NOT_plan_sha(monkeypatch, tmp_path):
    """The fixture the whole split exists for."""
    before_plan, before_board = planner._plan_sha(), planner._board_sha()

    original = REGISTRY.read_bytes()
    try:
        REGISTRY.write_bytes(original + b"\n# a widget spec edit\n")
        assert planner._board_sha() != before_board, "a spec edit must move board_sha"
        assert planner._plan_sha() == before_plan, (
            "a spec edit must NOT move plan_sha — that is what re-authors every "
            "objective and voids the review")
    finally:
        REGISTRY.write_bytes(original)
    assert planner._plan_sha() == before_plan
    assert planner._board_sha() == before_board


def test_editing_a_SEGMENT_function_moves_plan_sha():
    """The other direction: a change to how segments are authored must still
    regenerate, or a stale lesson is served forever."""
    before = planner._plan_sha()
    original = PLANNER.read_text()
    try:
        # append a comment OUTSIDE every board function
        PLANNER.write_text(original + "\n# segment-side edit\n")
        assert planner._plan_sha() != before
    finally:
        PLANNER.write_text(original)
    assert planner._plan_sha() == before


def test_the_reattach_REFUSES_if_it_would_change_an_objective():
    """Stated as a refusal in the code, asserted here.

    If a board pass ever moves an objective, the verdict store decays silently
    and nothing notices until a review is already void. That is precisely what
    happened on 2026-09-15, and it took a day to detect.
    """
    src = ast.unparse(ast.parse(PLANNER.read_text()))
    assert "refusing to write" in PLANNER.read_text()
    fn = next(n for n in ast.parse(PLANNER.read_text()).body
              if isinstance(n, ast.FunctionDef) and n.name == "_reattach_boards_in_place")
    body = ast.unparse(fn)
    assert "before != after" in body
    assert "raise RuntimeError" in body


def test_provenance_carries_both_hashes():
    prov = planner.plan_provenance()
    for k in ("plan_sha", "board_sha", "planner_code_sha", "planner_prompt_hash"):
        assert prov.get(k), f"{k} missing from plan_provenance()"
    assert len(prov["plan_sha"]) == 16 and len(prov["board_sha"]) == 16


def test_a_pre_split_row_still_regenerates_on_the_whole_file_hash():
    """Rows written before the split carry neither hash. They must fall back to
    planner_code_sha rather than being read as 'no drift' — an empty field is
    not agreement."""
    src = PLANNER.read_text()
    block = src[src.index("_stored = _plan_json_provenance(cached_plan)"):]
    block = block[:block.index("if _drift:")]
    assert "_has_split" in block
    assert "planner_code_sha" in block, (
        "the pre-split fallback must still compare the whole-file hash")
