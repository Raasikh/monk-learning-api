"""Does this illustration contain text? A detector, and an honest account of it.

The work order says the unlabelled master must contain "no text of any kind".
Step 3 of the ingest verifies that. This module is that verification, kept in
its own file so it can be MEASURED independently rather than trusted because it
was written.

WHY THIS FILE IS SHAPED AROUND ITS OWN LIMITS
=============================================
The recurring defect in this project is a check that passes because it found
nothing: `grounded` was always true, `topic_hash` was never populated,
`page_start` was always 1, a font-floor assertion was live for one commit and
matched nothing at all. Each looked like a green tick.

A text detector is the single easiest place to repeat that. "No text found" and
"no text present" are different statements, and only one of them is evidence.
So this module never returns a boolean. It returns a VERDICT with a named
method, and the caller is required to store which method produced it:

    ocr-clean                        real OCR ran and found nothing
    ocr-found-text                   real OCR found text (the refusal)
    heuristic-found-text             the shape heuristic found text (refusal)
    heuristic-clean-ocr-unavailable  the heuristic found nothing AND no OCR was
                                     installed. NOT a pass. It is the absence of
                                     evidence, recorded as such.
    unavailable                      neither detector could run at all

`heuristic-clean-ocr-unavailable` is the important one. It is stored in
concept_assets.text_check so that `select text_check, count(*)` says exactly how
many assets were never really checked — a queryable admission instead of a green
tick.


THE TWO DETECTORS
=================
OCR (preferred). pytesseract + the tesseract binary. NEITHER IS INSTALLED ON
THIS MACHINE and neither is in requirements.txt, so today this path never runs.
That is stated rather than hidden: with `brew install tesseract && pip install
pytesseract`, `probe()` upgrades itself to `ocr-clean` / `ocr-found-text` with
no other change, and every asset ingested before that carries a text_check value
that says it was ingested before that.

Shape heuristic (fallback, always available given numpy + scipy). Text is ink
that is glyph-shaped and arranged in a line:

  1. downscale so the long edge is WORK_EDGE, for a size-independent threshold;
  2. binarise against the paper tone (Otsu);
  3. connected components (8-connectivity);
  4. keep components that are glyph-SHAPED — bounded height, bounded aspect,
     and an ink fill ratio between a thin line and a solid blob;
  5. chain glyph-shaped components that share a baseline and sit close
     together; a chain of >= MIN_GLYPHS_PER_WORD is a word.

Step 5 is what separates a detector from a smudge counter. A single dark blob
of the right size is a nucleus, a spore or a stipple dot; three of them on a
common baseline at a common height is writing.


WHAT IT MISSES — MEASURED, NOT ESTIMATED
========================================
Reproduced by tests/test_asset_ingest.py::test_text_probe_measured_behaviour,
over synthetic plates: aged-paper ground, engraving-like polylines, closed
organ outlines, heavy stipple shading, and PIL-rendered serif labels with
leader lines. Numbers as measured on this machine, 30-40 plates per case:

    normal horizontal labels                    100%  (30/30)   detected
    labels overlapping the drawing's strokes    100%  (30/30)   detected
    mixed plates, 3-12 labels each              100%  (40/40)   detected
    rotated text, 25-90 degrees                  63%  (19/30)   detected
    single-character labels (A, B, C)              0%  ( 0/30)  MISSED
    large display text (~90px, a title)            0%  ( 0/30)  MISSED  *
    clean plates, no text                          0%  ( 0/40)  no false pos
    plates with regular rows of cells              0%  ( 0/30)  no false pos

    * caught by the second tier — see below.

TREAT THE RECALL FIGURES AS AN UPPER BOUND, NOT AS THE FIELD RATE. The
positives are PIL-rendered text on a synthetic ground. Real Gemini output in an
1886 engraving style is a harder distribution and these numbers will be worse
on it. What the measurement does establish is the SHAPE of the failure, and the
two total blind spots are real and are not hypothetical:

  * A one- or two-character label ("A", "II") is below MIN_GLYPHS_PER_WORD by
    construction. 0/30. There is no tuning that fixes this without flagging
    every stipple dot.
  * Display text above the glyph-height ceiling. 0/30 in the strict tier.

THE SECOND TIER, AND WHY IT IS A WARNING RATHER THAN A REFUSAL
==============================================================
Raising MAX_GLYPH_H from 44 to 70 was measured directly:

    ceiling      title detected     rows-of-cells false positive
      44             0/30                  0/30
      70            26/30                 30/30
     110            26/30                 30/30

So the large window buys display text at the cost of firing on EVERY plate with
a regular row of similar structures — a row of ovarioles, a row of cells, a
row of spores. That is a common biology-plate pattern, not a rare one.

Making that a hard refusal would fire on a large fraction of the 48 figures,
and a gate that fires constantly is a gate that gets overridden reflexively —
which is worse than the blind spot, because then it is not running at all while
still looking like it is. So the two windows are kept separate:

    STRICT tier (h <= 44)   -> `heuristic-found-text`, a hard refusal.
                               0 false positives across 70 measured plates.
    LARGE tier (45..160)    -> a WARNING on the result, never a refusal.
                               Catches titles; also fires on cell rows.

The bottom line, stated so it is not inferred: THIS HEURISTIC IS EVIDENCE OF
TEXT WHEN THE STRICT TIER FIRES, AND IS NOT EVIDENCE OF ABSENCE WHEN IT DOES
NOT. The ingest treats it that way — firing is a hard refusal, and not firing
requires an explicit, recorded acknowledgement rather than producing a pass.
"""
from __future__ import annotations

import io
from typing import Dict, List, Optional, Tuple

# The long edge everything is measured at, so a 1200px plate and a 4000px plate
# get the same glyph-size window. Text scales with the figure; a fixed pixel
# threshold on the original would only be right at one resolution.
WORK_EDGE = 1400

# Glyph shape window, in working-scale pixels. Derived from the work order's
# "direct labels with leader lines" at ~16:10: a label set of 10-28 terms on a
# 1400px-wide plate puts cap height in the 8-40px band.
MIN_GLYPH_H, MAX_GLYPH_H = 6, 44
MIN_GLYPH_W, MAX_GLYPH_W = 2, 48

# The second tier. Measured: this window catches ~87% of display text and also
# fires on 100% of plates with a regular row of similar structures, so it is
# advisory only and never refuses. See the docstring.
LARGE_GLYPH_H = (45, 160)
LARGE_GLYPH_W = (10, 170)
MIN_GLYPH_PX = 10
MIN_ASPECT, MAX_ASPECT = 0.08, 2.6
# A thin stroke fills little of its bbox; a solid blob fills almost all of it.
# A glyph is in between, and that is most of what distinguishes it from a
# leader line (low) and a stipple dot or a nucleus (high).
MIN_FILL, MAX_FILL = 0.10, 0.88

# Three glyphs on a baseline. Two is a pair of dots; three is writing.
MIN_GLYPHS_PER_WORD = 3
# Same-line tolerances, as multiples of glyph height.
BASELINE_TOL = 0.45
MAX_GAP = 1.4
MAX_HEIGHT_RATIO = 2.4

VERDICTS = (
    "ocr-clean",
    "ocr-found-text",
    "heuristic-found-text",
    "heuristic-clean-ocr-unavailable",
    "unavailable",
)

CLEAN_VERDICTS = ("ocr-clean", "heuristic-clean-ocr-unavailable")
TEXT_VERDICTS = ("ocr-found-text", "heuristic-found-text")


class Result:
    """A verdict, the method that produced it, and what it actually saw."""

    def __init__(self, verdict: str, detail: str,
                 words: Optional[List[Tuple[int, int, int, int]]] = None,
                 ocr_text: str = "", warnings: Optional[List[str]] = None):
        assert verdict in VERDICTS, verdict
        self.verdict = verdict
        self.detail = detail
        self.words = words or []
        self.ocr_text = ocr_text
        self.warnings = warnings or []

    @property
    def found_text(self) -> bool:
        return self.verdict in TEXT_VERDICTS

    @property
    def is_conclusive(self) -> bool:
        """True only when a detector that can actually read text has spoken."""
        return self.verdict in ("ocr-clean", "ocr-found-text",
                                "heuristic-found-text")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Result {self.verdict} {self.detail}>"


def _ocr(data: bytes) -> Optional[Result]:
    """Real OCR, if it is installed. Returns None when it is not.

    Returning None rather than a clean verdict is the whole point: an absent
    detector must not be able to produce a pass.
    """
    try:
        import pytesseract  # type: ignore
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(data)) as im:
            text = pytesseract.image_to_string(im.convert("L"))
    except Exception as err:
        # A configured-but-broken tesseract is not a clean plate either.
        return Result("unavailable", f"pytesseract failed: {err}")

    stripped = "".join(ch for ch in text if ch.isalnum())
    if len(stripped) >= 3:
        return Result("ocr-found-text",
                      f"OCR read {len(stripped)} alphanumeric characters",
                      ocr_text=text.strip())
    return Result("ocr-clean", "OCR read no words")


def _otsu(hist) -> int:
    """Classic Otsu on a 256-bin histogram. Aged paper vs ink is bimodal."""
    import numpy as np

    total = hist.sum()
    if total == 0:
        return 128
    levels = np.arange(256)
    sum_all = float((levels * hist).sum())
    w_b = 0.0
    sum_b = 0.0
    best_var, best_t = -1.0, 128
    for t in range(256):
        w_b += float(hist[t])
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += float(t * hist[t])
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best_var:
            best_var, best_t = var, t
    return best_t


def find_text_like(data: bytes, large: bool = False) -> List[Tuple[int, int, int, int]]:
    """Bounding boxes of glyph chains, in working-scale pixels.

    `large=True` selects the advisory display-text window instead of the strict
    label window. The two are deliberately separate tiers, not one widened one.

    Raises ImportError when numpy/scipy/Pillow are missing, which the caller
    turns into `unavailable` rather than into a pass.
    """
    import numpy as np
    from scipy import ndimage
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("L")
        scale = WORK_EDGE / max(im.size)
        if scale < 1:
            im = im.resize((max(1, int(im.width * scale)),
                            max(1, int(im.height * scale))),
                           Image.LANCZOS)
        arr = np.asarray(im, dtype=np.uint8)

    hist = np.bincount(arr.ravel(), minlength=256)
    ink = arr < _otsu(hist)

    labels, n = ndimage.label(ink, structure=np.ones((3, 3), dtype=int))
    if n == 0:
        return []

    glyphs: List[Tuple[int, int, int, int]] = []
    counts = ndimage.sum(ink, labels, index=np.arange(1, n + 1))
    for idx, sl in enumerate(ndimage.find_objects(labels)):
        if sl is None:
            continue
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        h, w = y1 - y0, x1 - x0
        h_lo, h_hi = LARGE_GLYPH_H if large else (MIN_GLYPH_H, MAX_GLYPH_H)
        w_lo, w_hi = LARGE_GLYPH_W if large else (MIN_GLYPH_W, MAX_GLYPH_W)
        if not (h_lo <= h <= h_hi):
            continue
        if not (w_lo <= w <= w_hi):
            continue
        px = float(counts[idx])
        if px < MIN_GLYPH_PX:
            continue
        if not (MIN_ASPECT <= w / h <= MAX_ASPECT):
            continue
        fill = px / float(h * w)
        if not (MIN_FILL <= fill <= MAX_FILL):
            continue
        glyphs.append((x0, y0, x1, y1))

    return _chain(glyphs)


def _chain(glyphs) -> List[Tuple[int, int, int, int]]:
    """Group glyph-shaped components sharing a baseline into words.

    This is the step that makes the detector a text detector rather than a
    smudge counter: one blob of glyph size is a nucleus, three in a row at a
    common height is writing.
    """
    if len(glyphs) < MIN_GLYPHS_PER_WORD:
        return []
    boxes = sorted(glyphs, key=lambda b: (b[1], b[0]))
    used = [False] * len(boxes)
    words = []

    for i, b in enumerate(boxes):
        if used[i]:
            continue
        chain = [b]
        used[i] = True
        cur = b
        for j in range(len(boxes)):
            if used[j]:
                continue
            c = boxes[j]
            hb, hc = cur[3] - cur[1], c[3] - c[1]
            if max(hb, hc) / max(1, min(hb, hc)) > MAX_HEIGHT_RATIO:
                continue
            cyb = (cur[1] + cur[3]) / 2
            cyc = (c[1] + c[3]) / 2
            if abs(cyb - cyc) > BASELINE_TOL * max(hb, hc):
                continue
            gap = c[0] - cur[2]
            if gap < -max(hb, hc) or gap > MAX_GAP * max(hb, hc):
                continue
            chain.append(c)
            used[j] = True
            cur = c
        if len(chain) >= MIN_GLYPHS_PER_WORD:
            words.append((min(x[0] for x in chain), min(x[1] for x in chain),
                          max(x[2] for x in chain), max(x[3] for x in chain)))
    return words


def probe(data: bytes) -> Result:
    """The verdict for one image. Never a bare boolean."""
    ocr = _ocr(data)
    if ocr is not None and ocr.verdict != "unavailable":
        return ocr

    try:
        words = find_text_like(data)
        large = [] if words else find_text_like(data, large=True)
    except ImportError as err:
        return Result(
            "unavailable",
            f"neither OCR nor the shape heuristic can run here ({err}). "
            f"Install pytesseract + tesseract, or numpy + scipy.",
        )
    except Exception as err:
        return Result("unavailable", f"the shape heuristic failed: {err}")

    if words:
        return Result(
            "heuristic-found-text",
            f"{len(words)} glyph chain(s) of >= {MIN_GLYPHS_PER_WORD} "
            f"baseline-aligned glyph-shaped components, e.g. at "
            f"{words[0]} (working scale, long edge {WORK_EDGE}px)",
            words=words,
        )

    warnings = []
    if large:
        warnings.append(
            f"the ADVISORY display-text tier found {len(large)} large glyph "
            f"chain(s), e.g. at {large[0]}. Measured, that tier catches ~87% of "
            f"titles and also fires on 100% of plates with a regular row of "
            f"similar structures, so this is not a refusal — look at the plate."
        )

    return Result(
        "heuristic-clean-ocr-unavailable",
        "the strict tier found no glyph chains, and no OCR engine is "
        "installed. This is the ABSENCE OF EVIDENCE, not evidence of absence. "
        "Measured blind spots: single-character labels 0/30 detected, and "
        "rotated text only 19/30.",
        warnings=warnings,
    )
