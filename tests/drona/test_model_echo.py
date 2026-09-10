"""The model-echo guard accepts known canonical aliases and nothing else.

Why this exists: on 2026-09-10 DeepSeek's API began echoing `deepseek-flash`
in stream chunks for a requested `deepseek-v4-flash`, and the strict equality
check in tutor.py raised STRICT R1 MODEL VIOLATION on the first chunk of every
live teaching turn — production taught nothing while every board looked fine
(the failure path auto-populates board items and serves precomputed widgets).
The fix is an explicit, evidence-dated alias map, not a loosened guard; these
tests pin both directions.
"""
from app.drona.models import KNOWN_MODEL_ECHOES, MODEL_TUTOR, model_echo_ok


def test_exact_echo_accepted():
    assert model_echo_ok("deepseek-v4-flash", "deepseek-v4-flash")


def test_known_alias_echo_accepted():
    # The 2026-09-10 outage shape: pinned request, canonical echo.
    assert model_echo_ok("deepseek-v4-flash", "deepseek-flash")


def test_empty_echo_accepted():
    # Some gateways omit `model` on chunks; nothing to compare is not a lie.
    assert model_echo_ok("deepseek-v4-flash", "")


def test_unknown_echo_refused():
    # The failing fixture for the guard: a genuinely different family must
    # still be refused — this is the substitution the guard exists to catch.
    assert not model_echo_ok("deepseek-v4-flash", "deepseek-r1")


def test_alias_is_directional():
    # The map reads requested -> allowed echoes; the reverse direction is not
    # implied. Requesting the canonical name and receiving the pinned one
    # would be a NEW observation and needs its own dated map entry.
    assert not model_echo_ok("deepseek-flash", "deepseek-v4-flash")


def test_tutor_model_outage_shape_is_covered():
    # The production tutor pin must accept the echo measured 2026-09-10, or
    # the exact outage this file documents comes straight back on deploy.
    assert model_echo_ok(MODEL_TUTOR, "deepseek-flash")
    assert MODEL_TUTOR in KNOWN_MODEL_ECHOES
