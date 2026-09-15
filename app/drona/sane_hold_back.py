"""Does this chapter's SANE verdict allow a registry widget to be BAKED?

    allowed, why = widget_baking_allowed("physics", 12, "Electric Charges and Fields")

THE RULE, from Raasikh's confirmation on 2026-09-14:

    "precompute all chapters with hold-back below 85%"

A registry widget bakes into slot 1 only where its chapter's SANE verdict is
at or above the bar. Below the bar, or with no verdict at all, the widget slot
is SKIPPED and the concept resolves down the precedence chain — illustration,
then precomputed SVG, then live SVG. Illustration slots do not depend on SANE
and always bake.

WHY THIS IS A HOLD-BACK AND NOT A FILTER
========================================
A widget that renders is not the same as a widget that is RIGHT. Session F got
every stored payload in every subject to render — 113 of 113 — and the two
worst errors found that week both rendered perfectly: an infinite line charge
drawn as a point charge, and a single charged sheet drawn as parallel plates,
each under a confident caption describing a figure that was not on the board.
No automated gate sees that. SANE is the measurement that does, and until a
chapter has been read by a person there is nothing to stand on.

So the bar is applied to BAKING, not to drawing. Held back, the live path still
asks per turn and the board still gets a picture; what it does not get is a
permanent cached picture, sitting in the highest-precedence slot, that nobody
has checked.

UNMEASURED IS HELD BACK, AND THAT IS THE POINT
==============================================
The recurring defect in this project is a check that PASSES on absent
information: `grounded` was always true, `topic_hash` was never populated,
`page_start` was hardcoded to 1 across 5,266 rows, a text detector that found
nothing was read as a figure containing nothing. Treating "no verdict" as
"fine" would be that defect written into a policy. A chapter with no verdict
is `unmeasured` and is held back exactly like a failing one, and the reason
string says which of the two it was so the report can tell them apart.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: The policy bar. One number for every chapter, deliberately not per row —
#: two chapters disagreeing about what "passing" means is the kind of drift
#: that surfaces as a blank board in a live class.
SANE_BAR_PERCENT = 85.0

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "content", "sane-verdicts.json")

#: Set by tests. None means "read the file".
_OVERRIDE: Optional[Dict[str, float]] = None

_CACHE: Optional[Dict[str, dict]] = None
LOAD_ERROR: Optional[str] = None


def _key(subject: str, class_level: int, chapter: str) -> str:
    return f"{(subject or '').strip().lower()}|{class_level}|{(chapter or '').strip().lower()}"


def _load() -> Dict[str, dict]:
    """Verdicts by key. A file that cannot be read yields NO verdicts, which
    holds everything back — the failure mode that costs a cached picture, not
    the one that ships an unchecked one."""
    global _CACHE, LOAD_ERROR
    if _CACHE is not None:
        return _CACHE
    try:
        with open(_PATH, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        out: Dict[str, dict] = {}
        for v in doc.get("verdicts") or []:
            out[_key(v["subject"], int(v["class_level"]), v["chapter"])] = v
        _CACHE = out
        LOAD_ERROR = None
    except Exception as exc:                      # noqa: BLE001
        LOAD_ERROR = f"{type(exc).__name__}: {exc}"
        logger.error("[SANE] could not read %s: %s — every chapter is now "
                     "UNMEASURED and every widget slot is held back", _PATH, exc)
        _CACHE = {}
    return _CACHE


def reset_cache() -> None:
    """For tests, and for a long-running process that has just had the file
    rewritten under it."""
    global _CACHE
    _CACHE = None


def sane_percent(subject: str, class_level: int, chapter: str) -> Optional[float]:
    """The chapter's verdict, or None for unmeasured."""
    if _OVERRIDE is not None:
        return _OVERRIDE.get(_key(subject, class_level, chapter))
    v = _load().get(_key(subject, class_level, chapter))
    return None if v is None else float(v["sane_percent"])


def widget_baking_allowed(subject: str, class_level: int,
                          chapter: str) -> Tuple[bool, str]:
    """(allowed, reason). The reason is written into the precompute record, so
    a held-back concept says WHY it was held back rather than looking like a
    concept that had no widget."""
    pct = sane_percent(subject, class_level, chapter)
    if pct is None:
        return False, "held back: chapter SANE is unmeasured"
    if pct < SANE_BAR_PERCENT:
        return False, (f"held back: chapter SANE {pct:.1f}% is below the "
                       f"{SANE_BAR_PERCENT:.0f}% bar")
    return True, f"chapter SANE {pct:.1f}% clears the {SANE_BAR_PERCENT:.0f}% bar"
