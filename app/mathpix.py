"""Mathpix OCR — reads the maths off a photo before any model sees it.

Why a specialist sits in front of the vision model, measured on real pages:

    case                        gpt-4o-mini              Mathpix
    JEE Q2 options              lost "3 - e", duplicated  exact
    magnetic-field options      flattened, invented a 4th exact, 3 options
    hydrogen crop (bad photo)   wrong                     wrong, confidence 0.48

Mathpix is OCR, not generation: it cannot invent an option that is not on the
page, which is the failure that produced two confidently wrong answers. It also
returns a confidence score, so an unreliable read is detectable instead of
silently wrong.

The structuring model that runs after this never sees the image — it only
reshapes Mathpix's LaTeX into questions and options, so it cannot corrupt the
maths either.
"""
import logging
import os
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("mathpix")

MATHPIX_URL = "https://api.mathpix.com/v3/text"
MATHPIX_TIMEOUT_S = 45.0

# Mathpix returns TWO scores and they mean different things:
#
#   confidence       P(the whole result is perfect) — falls off a cliff on long
#                    pages regardless of quality
#   confidence_rate  the estimated fraction of elements recognised correctly
#
# Measured across seven real pages (transcription checked by hand):
#
#   page                              confidence   confidence_rate  verdict
#   JEE Q11-Q18                          0.434         0.9936       perfect
#   JEE Q1-Q8                            0.712         0.9975       perfect
#   chemistry page                       0.670         0.9697       perfect
#   magnetic field                       0.944         0.9982       perfect
#   wave equation                        0.449         0.9936       perfect
#   hydrogen crop                        0.481         0.9293       MISREAD
#   stem-only crop                       0.982         0.9997       perfect
#
# `confidence` does not separate good from bad at all — perfect reads span
# 0.43-0.94 and the one real misread sits at 0.48, in the middle of them. Gating
# on it refused a page that had been transcribed flawlessly. `confidence_rate`
# does separate them, but only just: 0.9293 bad against 0.9697 worst-good.
#
# So this is a FLOOR for catastrophically bad reads, not a precision instrument.
# It is set below the one known-bad sample rather than snugly above it, because
# tuning a threshold to a single example produces false refusals on real
# students' photos. Subtle misreads are caught downstream instead — the hydrogen
# page was ultimately stopped by the option-matching gate, which is where a
# wrong read shows up as a result matching none of the choices.
#
# Seven samples cannot calibrate this properly. Revisit with a real run.
MIN_CONFIDENCE_RATE = 0.90


class MathpixNotConfigured(RuntimeError):
    """Credentials absent. Raised rather than silently skipping OCR."""


class MathpixError(RuntimeError):
    """The OCR call failed or returned nothing usable."""


def _credentials() -> Dict[str, str]:
    # NOTE: the app id is spelled MATHPX_APP_ID in dronav1project/.env. Both
    # spellings are accepted so a corrected env does not break this.
    app_id = (os.getenv("MATHPIX_APP_ID") or os.getenv("MATHPX_APP_ID") or "").strip()
    app_key = (os.getenv("MATHPIX_APP_KEY") or "").strip()
    if not app_id or not app_key:
        missing = [n for n, v in (("MATHPIX_APP_ID", app_id),
                                  ("MATHPIX_APP_KEY", app_key)) if not v]
        raise MathpixNotConfigured(
            "Mathpix is not configured on this server. Missing: " + ", ".join(missing)
        )
    return {"app_id": app_id, "app_key": app_key}


def is_configured() -> bool:
    try:
        _credentials()
        return True
    except MathpixNotConfigured:
        return False


def read_page(image_bytes: bytes, mime_type: str,
              doubt_id: str = "-") -> Dict[str, Any]:
    """OCRs one photo. Returns {'text': latex, 'confidence': float}.

    Math comes back in $…$ / $$…$$ delimiters, which is what both the solver
    prompt and the frontend KaTeX renderer already expect.
    """
    creds = _credentials()

    import json as _json
    options = {
        "math_inline_delimiters": ["$", "$"],
        "math_display_delimiters": ["$$", "$$"],
        "rm_spaces": True,
        # Chemical structures are drawn, so plain OCR files them as diagram
        # regions and DROPS them from the text. Measured: a stereoisomer
        # question reached the solver as "the given molecule" with no molecule,
        # and it confabulated an answer. include_smiles converts the structure
        # to SMILES inline — <smiles>CC=CC(C)O</smiles> — so the molecule
        # travels with the question.
        "include_smiles": True,
        # Line data tells us whether the page actually contains a figure. That
        # is a hard signal from the OCR engine: a text-only model downstream
        # cannot see a diagram, and inferring one from wording alone missed a
        # real figure question ("two arrangements of wires" with no "as shown").
        "include_line_data": True,
    }

    t0 = time.time()
    logger.info(
        "[MATHPIX] doubt=%s POST %s image=%.1fKB mime=%s timeout=%ss",
        doubt_id[:8], MATHPIX_URL, len(image_bytes) / 1024, mime_type,
        MATHPIX_TIMEOUT_S,
    )
    try:
        res = requests.post(
            MATHPIX_URL,
            headers=creds,
            files={"file": (f"snap.{mime_type.split('/')[-1]}", image_bytes, mime_type)},
            data={"options_json": _json.dumps(options)},
            timeout=MATHPIX_TIMEOUT_S,
        )
    except requests.RequestException as err:
        logger.error("[MATHPIX] doubt=%s FAILED after %dms: %s",
                     doubt_id[:8], int((time.time() - t0) * 1000), err)
        raise MathpixError(f"Mathpix request failed: {err}")
    ocr_ms = int((time.time() - t0) * 1000)

    if res.status_code != 200:
        logger.error("[MATHPIX] doubt=%s HTTP %d in %dms: %s",
                     doubt_id[:8], res.status_code, ocr_ms, res.text[:200])
        raise MathpixError(f"Mathpix returned HTTP {res.status_code}: {res.text[:200]}")

    payload = res.json()
    if payload.get("error"):
        logger.error("[MATHPIX] doubt=%s API error in %dms: %s",
                     doubt_id[:8], ocr_ms, payload["error"])
        raise MathpixError(f"Mathpix error: {payload['error']}")

    line_types = [ln.get("type") for ln in (payload.get("line_data") or [])]
    diagram_regions = sum(1 for t in line_types if t in ("diagram", "chart"))

    text = (payload.get("text") or "").strip()
    rate = payload.get("confidence_rate")
    rate = float(rate) if rate is not None else None
    whole_page = payload.get("confidence")
    whole_page = float(whole_page) if whole_page is not None else None

    if not text:
        logger.error("[MATHPIX] doubt=%s read NOTHING in %dms (confidence_rate=%s)",
                     doubt_id[:8], ocr_ms,
                     f"{rate:.4f}" if rate is not None else "n/a")
        raise MathpixError("Mathpix read nothing from that image.")

    logger.info(
        "[MATHPIX] doubt=%s ocr_ms=%d chars=%d confidence_rate=%s "
        "page_confidence=%s diagram_regions=%d lines=%d",
        doubt_id[:8], ocr_ms, len(text),
        f"{rate:.4f}" if rate is not None else "n/a",
        f"{whole_page:.4f}" if whole_page is not None else "n/a",
        diagram_regions, len(line_types),
    )
    return {"text": text, "confidence": rate, "page_confidence": whole_page,
            "diagram_regions": diagram_regions, "ocr_ms": ocr_ms}


def confidence_is_usable(confidence_rate: Optional[float]) -> bool:
    """True when the read is trustworthy enough to solve from.

    Takes `confidence_rate`, not `confidence`. An absent score is treated as
    usable — Mathpix omits it on some responses, and refusing on a missing field
    would reject good pages.
    """
    return confidence_rate is None or confidence_rate >= MIN_CONFIDENCE_RATE
