"""Record what every model call cost, so spend is answerable from the database.

Written 2026-08-15. On that day deepseek-v4-pro billed $8.86 across 10,937
requests and nothing in the database could say why: drona_sessions.cost_usd was
declared `not null default 0` and never written, and the planner - the expensive
path - recorded neither tokens nor cost. Reconstructing the day took hours and
still did not identify the caller.

Two rules follow from that, and both matter more than the numbers:

1. TOKENS ARE RECORDED, COST IS DERIVED. Token counts come from the provider's
   own usage object and are always true. Prices change and are not in this
   codebase's control, so cost is computed from a configured table and is left
   NULL when that table has no entry.

2. AN UNPRICED CALL IS NULL, NOT ZERO. `drona_sessions.cost_usd = 0.0000` read
   as "this session was free" when it meant "nobody wrote this". Null cannot be
   misread that way, and a null with real token counts beside it still answers
   the question that mattered: what was actually called, and how much did it
   move.

Prices are set per model via environment, in USD per MILLION tokens, at
DeepSeek's PEAK rate:

    DEEPSEEK_PRICE_DEEPSEEK_V4_PRO="in=1.32,cached=0.044,out=3.96"

Peak, specifically, because DeepSeek bills two rates: off-peak is exactly half
of peak, and peak runs 01:00-04:00 and 06:00-10:00 UTC on weekdays. A single
configured number would therefore be wrong by 2x for most of the day in one
direction or the other. `cost_for` applies the halving itself from the call's
own timestamp, so what is configured is one rate and what is recorded is the
rate that actually applied.

Nothing here ships a default price. A guessed price produces a plausible,
wrong, and confidently-reported number, which is worse than no number at all.
"""
import logging
import os
import re
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

logger = logging.getLogger("drona.usage")

_WARNED_UNPRICED: set = set()

# For callers on a live student path: a PostgREST stall (default timeout is
# 120s) must never hold a solve hostage to its own accounting. Workers are
# non-daemon, so pending rows are flushed before the process exits.
_RECORD_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="llm-usage")


def _model_slug(model: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", model.upper())


def _env_key(model: str) -> str:
    """The name to TELL people to set. LLM_PRICE_* reads better now that the
    priced models include OpenAI's — DEEPSEEK_PRICE_GPT_4O_MINI is a confusing
    thing to find in an env file."""
    return "LLM_PRICE_" + _model_slug(model)


def _env_keys(model: str) -> tuple:
    """Both accepted names, preferred first. DEEPSEEK_PRICE_* stays supported
    because it is what is already configured in deployed environments."""
    slug = _model_slug(model)
    return ("LLM_PRICE_" + slug, "DEEPSEEK_PRICE_" + slug)


def price_for(model: str) -> Optional[Dict[str, float]]:
    """Per-million-token prices for a model, or None when unconfigured."""
    raw = None
    for key in _env_keys(model):
        raw = os.getenv(key)
        if raw:
            break
    if not raw:
        return None
    out: Dict[str, float] = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        try:
            out[k.strip().lower()] = float(v)
        except ValueError:
            return None
    return out or None


# DeepSeek's peak windows, in UTC hours, Monday-Friday. Outside these — and all
# weekend — every rate is halved. Published at
# https://api-docs.deepseek.com/quick_start/pricing
_PEAK_WINDOWS_UTC = ((1, 4), (6, 10))
OFF_PEAK_MULTIPLIER = 0.5


def is_peak(when: Optional[datetime] = None) -> bool:
    """Whether DeepSeek's peak rate applies at `when` (default: now, UTC)."""
    t = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if t.weekday() >= 5:  # Saturday, Sunday: off-peak throughout
        return False
    return any(start <= t.hour < end for start, end in _PEAK_WINDOWS_UTC)


def has_time_of_day_pricing(model: str) -> bool:
    """Whether this provider discounts by the clock. ONLY DeepSeek does.

    The halving below was written when DeepSeek was the only priced model and
    was applied to every model unconditionally. OpenAI bills one flat rate, so
    pricing gpt-4o-mini under that rule would have recorded its cost at half
    for most of the day and all weekend — a wrong number reported confidently,
    which is the exact failure this module's docstring warns about.
    """
    return model.lower().startswith("deepseek")


def cost_for(model: str, input_tokens: int, cache_hit_tokens: int,
             output_tokens: int, when: Optional[datetime] = None) -> Optional[float]:
    """USD for one call, or None when the model has no configured price.

    Cached input is billed separately, so it is subtracted from the input count
    rather than double-counted. For DeepSeek the configured prices are PEAK
    rates and an off-peak call is recorded at half; every other provider bills
    one flat rate and is costed as configured, whatever the clock says.
    """
    prices = price_for(model)
    if not prices:
        if model not in _WARNED_UNPRICED:
            _WARNED_UNPRICED.add(model)
            logger.warning(
                f"[USAGE] no price configured for {model!r} - set {_env_key(model)} "
                f"(USD per 1M tokens, e.g. 'in=0.15,cached=0.075,out=0.60'; "
                f"for DeepSeek give the PEAK rate — off-peak is halved for you). "
                f"Tokens are still recorded; cost_usd stays NULL."
            )
        return None
    fresh_in = max(0, (input_tokens or 0) - (cache_hit_tokens or 0))
    rate = 1.0
    if has_time_of_day_pricing(model) and not is_peak(when):
        rate = OFF_PEAK_MULTIPLIER
    return round(
        rate * (
            fresh_in / 1_000_000 * prices.get("in", 0.0)
            + (cache_hit_tokens or 0) / 1_000_000 * prices.get("cached", prices.get("in", 0.0))
            + (output_tokens or 0) / 1_000_000 * prices.get("out", 0.0)
        ),
        6,
    )


def tokens_from(res: Any) -> Dict[str, int]:
    """Pull token counts off an OpenAI-shaped response, tolerating absence."""
    usage = getattr(res, "usage", None)
    if usage is None:
        return {"input_tokens": 0, "cache_hit_tokens": 0, "output_tokens": 0}
    details = getattr(usage, "prompt_tokens_details", None)
    return {
        "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "cache_hit_tokens": (getattr(details, "cached_tokens", 0) or 0) if details else 0,
        "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
    }


def record_call(model: str, service: str, *, ok: bool = True, attempt: int = 1,
                res: Any = None, tokens: Optional[Dict[str, int]] = None,
                latency_ms: Optional[int] = None, session_id: Optional[str] = None,
                plan_id: Optional[str] = None, chapter_id: Optional[str] = None,
                subtopic_key: Optional[str] = None, user_id: Optional[str] = None,
                error: Optional[str] = None) -> None:
    """Persist one model call to `llm_calls`.

    Never raises. Accounting must not be able to fail a live turn - but it does
    log, because a silent accounting failure is how the original gap persisted.

    Call it for FAILED calls too. The calls that billed and threw their result
    away are the ones that were impossible to see, and they are the reason this
    module exists.
    """
    tok = tokens or tokens_from(res)
    # All-None token counts mean "billed an unknown amount" (e.g. a stream that
    # died before its usage chunk). Cost stays NULL there: pricing zero known
    # tokens would report the call as free, the exact misreading rule 2 forbids.
    counts_known = any(tok.get(k) is not None for k in
                       ("input_tokens", "cache_hit_tokens", "output_tokens"))
    try:
        from app.db import supabase
        supabase.table("llm_calls").insert([{
            "model": model,
            "service": service,
            "ok": ok,
            "attempt": attempt,
            "input_tokens": tok.get("input_tokens"),
            "cache_hit_tokens": tok.get("cache_hit_tokens"),
            "output_tokens": tok.get("output_tokens"),
            "cost_usd": cost_for(model, tok.get("input_tokens") or 0,
                                 tok.get("cache_hit_tokens") or 0,
                                 tok.get("output_tokens") or 0)
                        if counts_known else None,
            "latency_ms": latency_ms,
            "session_id": session_id,
            "plan_id": plan_id,
            "chapter_id": chapter_id,
            "subtopic_key": subtopic_key,
            "user_id": user_id,
            "error": (error or None) and str(error)[:500],
        }]).execute()
    except Exception as exc:
        logger.error(
            f"[USAGE] failed to record {service}/{model} "
            f"(in={tok.get('input_tokens')} out={tok.get('output_tokens')} ok={ok}): {exc}"
        )


def record_call_bg(*args, **kwargs) -> None:
    """`record_call`, off the caller's thread. For live student paths.

    The insert runs on `_RECORD_EXECUTOR`; the caller returns immediately, so a
    slow or hung PostgREST round-trip cannot delay a turn. Same never-raises
    contract. `record_call` is resolved at execution time so tests that stub it
    out stub this too.
    """
    try:
        _RECORD_EXECUTOR.submit(lambda: record_call(*args, **kwargs))
    except Exception as exc:  # executor shut down during interpreter exit
        logger.error(f"[USAGE] failed to queue usage record: {exc}")
