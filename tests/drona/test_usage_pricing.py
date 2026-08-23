"""Cost is derived from tokens, and only when a price is actually configured.

DeepSeek bills two rates for the same call: off-peak is exactly half of peak,
and peak runs 01:00-04:00 and 06:00-10:00 UTC on weekdays only. A single
configured price applied around the clock would therefore be wrong by 2x for
most of the day — quietly, in whichever direction the configured rate leaned.
Since every cost figure in the product derives from this function, that error
would propagate to all of them.

Published rates: https://api-docs.deepseek.com/quick_start/pricing
"""

from datetime import datetime, timezone

import pytest

from app.drona import usage
from app.drona.usage import cost_for, is_peak, price_for

PRO_PEAK = "in=1.32,cached=0.044,out=3.96"


def at(day: int, hour: int) -> datetime:
    """A UTC instant in a known week. 2026-08-17 is a Monday, so day=0 is Mon."""
    return datetime(2026, 8, 17 + day, hour, 30, tzinfo=timezone.utc)


# ── Rule 2: an unpriced call is NULL, not zero ───────────────────────────────

def test_an_unconfigured_model_costs_none_not_zero(monkeypatch):
    # BOTH names must go: a price can now be set as LLM_PRICE_* (preferred) or
    # DEEPSEEK_PRICE_* (what deployed environments already carry). Clearing
    # only one left the other configured, so this asserted "unpriced" against a
    # model that was still priced.
    monkeypatch.delenv("LLM_PRICE_DEEPSEEK_V4_PRO", raising=False)
    monkeypatch.delenv("DEEPSEEK_PRICE_DEEPSEEK_V4_PRO", raising=False)
    # Zero would read as "this call was free". It was not free; it was unpriced.
    assert cost_for("deepseek-v4-pro", 10_000, 0, 1_000) is None


def test_a_malformed_price_is_unpriced_rather_than_partially_applied(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_PRICE_DEEPSEEK_V4_PRO", raising=False)
    monkeypatch.setenv("LLM_PRICE_DEEPSEEK_V4_PRO", "in=notanumber,out=3.96")
    # Half a price table produces a confidently wrong number, which rule 2
    # exists to prevent. Refuse the whole entry.
    assert price_for("deepseek-v4-pro") is None
    assert cost_for("deepseek-v4-pro", 10_000, 0, 1_000) is None


def test_either_env_name_prices_a_model(monkeypatch):
    """LLM_PRICE_* is preferred; DEEPSEEK_PRICE_* still works.

    Deployed environments were configured under the old name before OpenAI
    models were priced, and DEEPSEEK_PRICE_GPT_4O_MINI is a confusing thing to
    ask anyone to set. Both resolve; the new name wins when both are present.
    """
    monkeypatch.delenv("LLM_PRICE_DEEPSEEK_V4_PRO", raising=False)
    monkeypatch.setenv("DEEPSEEK_PRICE_DEEPSEEK_V4_PRO", "in=1.32,cached=0.044,out=3.96")
    assert price_for("deepseek-v4-pro")["in"] == 1.32
    monkeypatch.setenv("LLM_PRICE_DEEPSEEK_V4_PRO", "in=9.99,cached=1.0,out=9.99")
    assert price_for("deepseek-v4-pro")["in"] == 9.99


def test_openai_is_not_given_deepseeks_off_peak_discount(monkeypatch):
    """Only DeepSeek discounts by the clock.

    The halving was applied to every model, because DeepSeek was the only one
    priced. Pricing gpt-4o-mini under that rule recorded it at half for most of
    the day and all weekend — a confidently wrong number, which is the failure
    this module exists to prevent.
    """
    from datetime import datetime, timezone
    monkeypatch.setenv("LLM_PRICE_GPT_4O_MINI", "in=0.15,cached=0.075,out=0.60")
    monkeypatch.setenv("LLM_PRICE_DEEPSEEK_V4_PRO", "in=1.32,cached=0.044,out=3.96")
    peak = datetime(2026, 8, 24, 7, 0, tzinfo=timezone.utc)   # Monday, in-window
    off = datetime(2026, 8, 23, 20, 0, tzinfo=timezone.utc)   # Sunday, always off

    mini_peak = cost_for("gpt-4o-mini", 10_000, 0, 5_000, when=peak)
    mini_off = cost_for("gpt-4o-mini", 10_000, 0, 5_000, when=off)
    assert mini_peak == mini_off, "OpenAI bills one flat rate at any hour"

    pro_peak = cost_for("deepseek-v4-pro", 10_000, 0, 5_000, when=peak)
    pro_off = cost_for("deepseek-v4-pro", 10_000, 0, 5_000, when=off)
    assert pro_off == pytest.approx(pro_peak / 2), "DeepSeek halves off-peak"


# ── Peak windows ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("hour", [1, 2, 3, 6, 8, 9])
def test_weekday_peak_hours(hour):
    assert is_peak(at(0, hour)) is True


@pytest.mark.parametrize("hour", [0, 4, 5, 10, 11, 15, 23])
def test_weekday_off_peak_hours(hour):
    # 04:00 and 10:00 are the exclusive upper bounds of the two windows.
    assert is_peak(at(0, hour)) is False


@pytest.mark.parametrize("day", [5, 6])
def test_weekends_are_off_peak_even_during_peak_hours(day):
    assert is_peak(at(day, 2)) is False
    assert is_peak(at(day, 8)) is False


def test_a_non_utc_timestamp_is_converted_before_comparing(monkeypatch):
    # Rows carry timezone-aware timestamps that are not necessarily UTC. Reading
    # the hour off one without converting would misclassify by the offset.
    from datetime import timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    # 07:30 UTC = 13:00 IST — peak, but only if the conversion happens.
    assert is_peak(datetime(2026, 8, 17, 13, 0, tzinfo=ist)) is True


# ── The halving ──────────────────────────────────────────────────────────────

def test_off_peak_is_exactly_half_of_peak(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_PRICE_DEEPSEEK_V4_PRO", PRO_PEAK)
    peak = cost_for("deepseek-v4-pro", 10_000, 0, 1_000, when=at(0, 2))
    off = cost_for("deepseek-v4-pro", 10_000, 0, 1_000, when=at(0, 15))
    assert peak == pytest.approx(off * 2)


def test_peak_cost_matches_the_published_rate_card(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_PRICE_DEEPSEEK_V4_PRO", PRO_PEAK)
    # 1M fresh input at 1.32 + 1M output at 3.96, at peak.
    assert cost_for("deepseek-v4-pro", 1_000_000, 0, 1_000_000,
                    when=at(0, 2)) == pytest.approx(5.28)


def test_cached_input_is_billed_once_at_the_cache_rate(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_PRICE_DEEPSEEK_V4_PRO", PRO_PEAK)
    # 1M prompt tokens of which 900k were cache hits: 100k fresh at 1.32 plus
    # 900k cached at 0.044 — NOT 1M at the fresh rate plus the cached charge
    # on top, which is what double-counting would produce.
    got = cost_for("deepseek-v4-pro", 1_000_000, 900_000, 0, when=at(0, 2))
    assert got == pytest.approx(0.1 * 1.32 + 0.9 * 0.044)


def test_a_fully_cached_prompt_never_goes_negative(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_PRICE_DEEPSEEK_V4_PRO", PRO_PEAK)
    # cache_hit_tokens can equal or briefly exceed prompt_tokens in provider
    # usage objects; the fresh-token count must floor at zero.
    assert cost_for("deepseek-v4-pro", 1000, 1200, 0, when=at(0, 2)) >= 0


def test_off_peak_multiplier_is_the_documented_half():
    assert usage.OFF_PEAK_MULTIPLIER == 0.5
