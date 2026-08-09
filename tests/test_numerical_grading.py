"""Tests for numerical answer grading (app/routers/practice.py).

Covers the regression that shipped to production: grading used a hardcoded
absolute 1e-3 and never read `value_tolerance`, so a student answering 9.8
against a key of 9.81 was marked wrong.

Runs under pytest, or standalone:  python3 tests/test_numerical_grading.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routers.practice import (  # noqa: E402
    grade_numerical,
    NUMERIC_REL_FRACTION,
    NUMERIC_ABS_FLOOR,
)


# --- the three cases named in the repair directive -------------------------

def test_rounded_answer_is_accepted():
    """key 9.81 accepts 9.8 -- the exact case the old 1e-3 rule rejected."""
    assert grade_numerical(9.8, 9.81) is True


def test_large_magnitude_answer_is_accepted():
    """key 6.02e23 accepts 6.03e23 -- unreachable under any absolute tolerance."""
    assert grade_numerical(6.03e23, 6.02e23) is True


def test_small_magnitude_wrong_answer_is_rejected():
    """key 0.001 rejects 0.01 -- an order of magnitude out must not pass."""
    assert grade_numerical(0.01, 0.001) is False


# --- per-row tolerance is authoritative ------------------------------------

def test_explicit_tolerance_widens():
    assert grade_numerical(10.4, 10.0, tolerance=0.5) is True


def test_explicit_tolerance_narrows():
    # 0.5% of 100 would be 0.5 and would accept; an explicit 0.01 must not.
    assert grade_numerical(100.4, 100.0, tolerance=0.01) is False


def test_zero_and_none_tolerance_fall_back():
    # NULL in the DB arrives as None; 0 must not mean "exact match only".
    assert grade_numerical(9.8, 9.81, tolerance=None) is True
    assert grade_numerical(9.8, 9.81, tolerance=0) is True


# --- corpus edge cases (measured from the 390 live numerical rows) ---------

def test_zero_key_requires_essentially_exact():
    """11 rows have correct_value == 0; only the absolute floor applies there."""
    assert grade_numerical(0.0, 0.0) is True
    assert grade_numerical(1e-7, 0.0) is True     # inside the floor
    assert grade_numerical(0.5, 0.0) is False


def test_adjacent_integers_stay_distinct_in_the_common_range():
    """Keys below 200 cover ~83% of the corpus; a neighbouring integer must fail."""
    for key in (1, 8, 10, 12, 65, 100, 199):
        assert grade_numerical(key + 1, key) is False, f"key={key} wrongly accepted key+1"
        assert grade_numerical(key, key) is True


def test_corpus_extremes():
    assert grade_numerical(0.06, 0.06) is True        # smallest non-zero key
    assert grade_numerical(65544, 65544) is True      # largest key
    assert grade_numerical(65544 * 1.02, 65544) is False   # 2% out must fail


def test_large_integer_keys_reject_adjacent_integers():
    """The 0.5% band exceeds 1 at |key| >= 200, so integer keys there are capped.

    Closes the gap for the 67 rows with |correct_value| >= 100 without waiting
    on per-question value_tolerance.
    """
    assert grade_numerical(201, 200) is False
    assert grade_numerical(200, 200) is True
    assert grade_numerical(200.4, 200) is True     # inside the 0.5 cap
    assert grade_numerical(200.6, 200) is False    # outside it
    # every integer key up the corpus range keeps its neighbours distinct
    for key in (200, 1000, 8630, 25600, 65544):
        assert grade_numerical(key + 1, key) is False, f"key={key} accepted key+1"
        assert grade_numerical(key, key) is True


def test_cap_does_not_apply_to_non_integer_keys():
    """A key of 250.5 is not integer-valued, so it keeps the full relative band."""
    assert grade_numerical(251.0, 250.5) is True   # 0.5% of 250.5 is ~1.25


def test_cap_does_not_apply_above_the_ceiling():
    """6.02e23 is integer-valued as a float; capping it at 0.5 would be absurd."""
    assert grade_numerical(6.03e23, 6.02e23) is True


def test_constants_are_sane():
    # the binding constraint is 6.02e23 -> 6.03e23, which needs >= 0.166%
    assert NUMERIC_REL_FRACTION >= 0.00166
    assert NUMERIC_ABS_FLOOR < 0.009   # must not let 0.01 pass against a 0.001 key


if __name__ == "__main__":
    failures = 0
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
