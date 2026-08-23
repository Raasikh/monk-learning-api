"""Trim a snapped photo down to the page before it is OCR'd.

Students photograph a whole screen. A real submission was a 1306KB browser-window
screenshot in which the PDF column was ~40% of the frame and the rest was tabs,
a bookmarks bar and a thumbnail rail — and Mathpix came back having found one
question out of six.

Measured on a page of six questions rendered inside a browser frame, with the
tiled watermarks a real paper carries:

    full frame     2400ms   109KB   page_confidence 0.150
    cropped        1934ms    93KB   page_confidence 0.431

So the crop is worth doing on its own: less to read, read better, and every bit
of browser furniture removed is furniture the structuring model cannot mistake
for a question.

Pillow only, deliberately. The obvious implementation wants numpy for row and
column profiles; resizing the mask to one pixel tall (or wide) averages each
column (or row) in C and costs ~15MB less on the server.
"""
import io
import logging
from typing import Optional, Tuple

logger = logging.getLogger("snap.image_prep")

# A pixel belongs to "the page" when it is bright and unsaturated — paper, not a
# toolbar. 150 keeps off-white scans; the saturation test rejects the coloured
# chrome that browsers paint at similar brightness.
_BRIGHT = 150
_MAX_SATURATION = 40
# A row/column counts as page when this much of it is bright. High enough that a
# white icon in a dark toolbar cannot drag the bounding box open.
_COVERAGE = 0.30
# Below this the crop is not worth the risk of trimming something real.
_MIN_SIDE_PX = 200
# If the bright region is already most of the frame, this is a photo of a page
# rather than a screenshot of one — leave it alone.
_ALREADY_PAGE = 0.75
_PAD_PX = 8


def _profile(mask, size: int, horizontal: bool) -> list:
    """Average brightness per column (horizontal) or per row, 0-255.

    Resizing to a 1px strip makes Pillow do the averaging in C, which is both
    faster than a Python loop and the reason this module needs no numpy.
    """
    from PIL import Image

    strip = mask.resize((size, 1) if horizontal else (1, size), Image.BILINEAR)
    return list(strip.getdata())


def crop_to_content(image_bytes: bytes, doubt_id: str = "-") -> Tuple[bytes, Optional[str]]:
    """Returns (possibly cropped bytes, description of what happened).

    Never raises and never returns something unusable: any doubt at all — a
    format Pillow cannot open, a region that looks wrong, a crop that would
    barely shrink the image — returns the original bytes untouched. A bad crop
    would remove the student's question, which is far worse than a slow read.
    """
    try:
        from PIL import Image
    except ImportError:
        return image_bytes, None

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        rgb = img.convert("RGB")
        w, h = rgb.size

        # Bright AND unsaturated, evaluated per pixel: min(r,g,b) high enough,
        # and max-min small. Built with band ops so Pillow stays in C.
        from PIL import ImageChops

        bands = rgb.split()
        lo = bands[0]
        hi = bands[0]
        for band in bands[1:]:
            lo = ImageChops.darker(lo, band)
            hi = ImageChops.lighter(hi, band)
        sat = ImageChops.subtract(hi, lo)

        bright = lo.point(lambda p: 255 if p > _BRIGHT else 0)
        flat = sat.point(lambda p: 255 if p < _MAX_SATURATION else 0)
        mask = ImageChops.multiply(bright, flat)

        cols = _profile(mask, w, horizontal=True)
        rows = _profile(mask, h, horizontal=False)
        floor = int(_COVERAGE * 255)
        xs = [i for i, v in enumerate(cols) if v > floor]
        ys = [i for i, v in enumerate(rows) if v > floor]
        if not xs or not ys:
            return image_bytes, None

        x0, x1 = xs[0], xs[-1] + 1
        y0, y1 = ys[0], ys[-1] + 1
        if (x1 - x0) < _MIN_SIDE_PX or (y1 - y0) < _MIN_SIDE_PX:
            return image_bytes, None

        ratio = ((x1 - x0) * (y1 - y0)) / float(w * h)
        if ratio > _ALREADY_PAGE:
            return image_bytes, None

        box = (max(0, x0 - _PAD_PX), max(0, y0 - _PAD_PX),
               min(w, x1 + _PAD_PX), min(h, y1 + _PAD_PX))
        out = io.BytesIO()
        rgb.crop(box).save(out, format="PNG")
        cropped = out.getvalue()

        # A "crop" that grew the payload has bought nothing; PNG-encoding a
        # photograph can easily beat its original JPEG.
        if len(cropped) >= len(image_bytes):
            return image_bytes, None

        note = (f"{w}x{h} -> {box[2]-box[0]}x{box[3]-box[1]} "
                f"({ratio:.0%} of frame, {len(image_bytes)/1024:.0f}KB -> "
                f"{len(cropped)/1024:.0f}KB)")
        logger.info("[SNAP CROP] doubt=%s %s", doubt_id[:8], note)
        return cropped, note
    except Exception as err:
        # Preprocessing must never be the reason a snap fails.
        logger.warning("[SNAP CROP] doubt=%s skipped: %s", doubt_id[:8], err)
        return image_bytes, None
