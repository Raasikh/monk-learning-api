"""Unit tests for the pure award math in app/progress_scoring.py.

Every expected value here is taken verbatim from the Progress spec (§4.2,
§4.3, §14's worked example), so a failing test means the code has drifted
from the product contract, not just from itself.
"""

import pytest

from app.progress_scoring import compute_mastery_updates, difficulty_band

CFG = {
    "g_base": 14,
    "l_base": 5,
    "secondary_concept_weight": 0.35,
    "strong_threshold": 80,
    "half_lives_days": [21, 45, 90],
    "difficulty_map": {"1": "easy", "2": "easy", "3": "medium", "4": "hard", "5": "pyq_hard", "null": "medium"},
    "difficulty_multipliers": {"easy": 0.7, "medium": 1.0, "hard": 1.4, "pyq_hard": 1.6},
}


def one(concept_id="c1", role="primary", mastery=0.0, **extra):
    row = {"mastery": mastery, "peak_mastery": mastery, "attempts_first": 0,
           "correct_first": 0, "proven_count": 0}
    row.update(extra)
    return {concept_id: row}


def run(mastery, is_correct, dq=1.0, role="primary", mode_mult=1.0, existing=None):
    updates = compute_mastery_updates(
        [("c1", role)], existing if existing is not None else one(mastery=mastery),
        is_correct, dq, CFG, mode_mult)
    return updates[0]


class TestSpecWorkedValues:
    def test_from_zero_medium_gives_14(self):
        assert run(0, True)["after"] == 14.0

    def test_from_60_medium_gives_5_6(self):
        assert run(60, True)["after"] == pytest.approx(65.6)

    def test_from_90_medium_gives_1_4(self):
        assert run(90, True)["after"] == pytest.approx(91.4)

    def test_wrong_at_80_costs_4(self):
        assert run(80, False)["after"] == pytest.approx(76.0)

    def test_wrong_at_20_costs_1(self):
        assert run(20, False)["after"] == pytest.approx(19.0)

    def test_section_14_session_sequence(self):
        """§14: six medium questions on a concept at 58, five right one wrong."""
        m = 58.0
        for step in ["+", "+", "+", "-", "+", "+"]:
            m = run(m, step == "+")["after"]
        assert m == pytest.approx(77.5, abs=0.1)


class TestDifficultyAndModes:
    def test_hard_multiplier(self):
        assert run(0, True, dq=1.4)["after"] == pytest.approx(19.6)

    def test_pyq_hard_multiplier(self):
        assert run(0, True, dq=1.6)["after"] == pytest.approx(22.4)

    def test_mock_premium(self):
        assert run(0, True, mode_mult=1.15)["after"] == pytest.approx(16.1)

    def test_band_mapping(self):
        assert difficulty_band(None, CFG) == "medium"
        assert difficulty_band(1, CFG) == "easy"
        assert difficulty_band(3, CFG) == "medium"
        assert difficulty_band(4, CFG) == "hard"
        assert difficulty_band(5, CFG) == "pyq_hard"
        assert difficulty_band(99, CFG) == "medium"  # unknown value → medium


class TestSecondaryConcepts:
    def test_secondary_gets_35_percent(self):
        u = run(0, True, role="secondary")
        assert u["after"] == pytest.approx(14 * 0.35)

    def test_secondary_loss_also_scaled(self):
        u = run(80, False, role="secondary")
        assert u["after"] == pytest.approx(80 - 4 * 0.35)

    def test_primary_and_secondary_together(self):
        existing = {"p": {"mastery": 0, "peak_mastery": 0, "attempts_first": 0,
                          "correct_first": 0, "proven_count": 0},
                    "s": {"mastery": 0, "peak_mastery": 0, "attempts_first": 0,
                          "correct_first": 0, "proven_count": 0}}
        ups = compute_mastery_updates([("p", "primary"), ("s", "secondary")],
                                      existing, True, 1.0, CFG)
        by_id = {u["concept_id"]: u for u in ups}
        assert by_id["p"]["after"] == 14.0
        assert by_id["s"]["after"] == pytest.approx(4.9)


class TestBoundsAndBookkeeping:
    def test_mastery_never_exceeds_100(self):
        assert run(99, True, dq=1.6)["after"] <= 100.0

    def test_mastery_never_below_0(self):
        assert run(0.5, False)["after"] >= 0.0

    def test_asymptote_easy_grind_cannot_fake_mastery(self):
        """§4.2: nine hundred easy questions cannot reach the ceiling."""
        m = 0.0
        for _ in range(900):
            m = run(m, True, dq=0.7)["after"]
        assert m < 100.0

    def test_peak_mastery_tracks_maximum(self):
        u = run(80, False, existing=one(mastery=80, peak_mastery=85))
        assert u["peak_mastery"] == 85.0

    def test_counters_increment(self):
        u = run(50, True, existing=one(mastery=50, attempts_first=7, correct_first=5))
        assert u["attempts_first"] == 8
        assert u["correct_first"] == 6
        u = run(50, False, existing=one(mastery=50, attempts_first=7, correct_first=5))
        assert u["attempts_first"] == 8
        assert u["correct_first"] == 5

    def test_reached_strong_flag(self):
        u = run(75, True)  # 75 + 14×0.25 = 78.5, still below 80
        assert u["after"] == pytest.approx(78.5)
        assert u["reached_strong"] is False
        u = run(79, True, dq=1.4)  # 79 + 14×1.4×0.21 ≈ 83.1
        assert u["after"] >= 80
        assert u["reached_strong"] is True

    def test_half_life_tier_from_proven_count(self):
        assert run(50, True, existing=one(mastery=50, proven_count=0))["half_life_days"] == 21
        assert run(50, True, existing=one(mastery=50, proven_count=1))["half_life_days"] == 45
        assert run(50, True, existing=one(mastery=50, proven_count=5))["half_life_days"] == 90
