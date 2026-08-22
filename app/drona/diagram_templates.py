"""Parameterised SVG diagram templates for Drona's live whiteboard.

WHY THIS MODULE IS FUSSY
========================
The SVG produced here is not rendered by a generic viewer. It is handed to
``PremiumBoardEvent.tsx`` in the web repo (``monk-learning-web``), which

1. **sanitises** it — ``<script>`` blocks and every ``on*`` attribute are
   stripped, so anything relying on them silently disappears;
2. **restyles** it — ``restyleSvgString`` does a literal string replace of a
   fixed set of source hex colours onto the house "chalk board" palette;
3. **animates** it — ``buildDrawPlan`` walks the SVG in *document order* and
   draws every ``path | line | polyline | polygon | circle | ellipse | rect``
   stroke-by-stroke using ``getTotalLength()``, while ``<text>`` fades in.

That turns into a contract every template in this file must honour. Break one
of these and the board shows a broken or invisible diagram:

* **Use only drawable primitives.** ``path``, ``line``, ``polyline``,
  ``polygon``, ``circle``, ``ellipse``, ``rect``. Anything else is not part of
  the draw plan and will not appear as a stroke.
* **Order the markup the way a teacher would draw it.** Document order *is*
  animation order. Axis before curve, box before the label inside it, wire
  before the component sitting on it.
* **Only emit the source colours in ``ALLOWED_COLORS``.** Any other hex is
  passed through untouched and will clash with the board palette. Note that
  ``#ffffff`` is remapped to ``transparent`` — that is deliberate, it is how a
  background rect lets the paper show through.
* **Never emit ``<script>``, ``on*`` attributes, ``<image>``, ``<foreignObject>``
  or any external reference.** Output must be a self-contained static SVG.
* **Always set an explicit ``viewBox``** and keep the whole string under
  ``MAX_SVG_CHARS`` (8000) — board events travel over the websocket.
* **Text fades, it does not draw.** Do not try to animate text via strokes, and
  do not set ``font-family``: ``restyleSvgString`` rewrites every
  ``font-family="..."`` to the app font anyway.
* **No ``<defs>``/``<marker>``.** Marker internals are explicitly excluded from
  the draw plan, so an arrowhead defined as a marker pops in before its line is
  drawn. Every arrowhead here is an explicit ``<polygon>`` emitted immediately
  after its line, so it draws in the right order.

All caller-supplied text is run through ``html.escape`` and length-capped, and
every entry point validates its arguments and raises ``ValueError`` rather than
emitting malformed SVG — labels arrive from an LLM and cannot be trusted.

Public surface: the eight template functions, the ``TEMPLATES`` registry and
``render(name, **kwargs)``.
"""

from __future__ import annotations

import html
import math
import textwrap
from typing import Any, Callable, Mapping, Sequence

# --------------------------------------------------------------------------
# palette — these exact source values are what restyleSvgString knows about
# --------------------------------------------------------------------------

INK = "#1f2933"
PRIMARY = "#2563eb"
LIGHT_FILL = "#dbeafe"
MUTED = "#64748b"
AMBER = "#d97706"
RED = "#dc2626"
GREEN = "#059669"
PALE_FILL = "#f1f5f9"
BACKGROUND = "#ffffff"

ALLOWED_COLORS = frozenset(
    {INK, PRIMARY, LIGHT_FILL, MUTED, AMBER, RED, GREEN, PALE_FILL, BACKGROUND}
)

MAX_SVG_CHARS = 8000

__all__ = [
    "ALLOWED_COLORS",
    "MAX_SVG_CHARS",
    "TEMPLATES",
    "boxed_derivation",
    "circuit_diagram",
    "comparison_table",
    "free_body_diagram",
    "labeled_axes_plot",
    "process_flow",
    "ray_diagram",
    "render",
    "vector_resolution",
]


# --------------------------------------------------------------------------
# validation + text helpers
# --------------------------------------------------------------------------


def _number(value: Any, field: str) -> float:
    """Coerce to a finite float or raise ValueError."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number, got {type(value).__name__}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{field} must be finite, got {value!r}")
    return out


def _sequence(value: Any, field: str, *, min_len: int, max_len: int) -> list[Any]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be a list or tuple, got {type(value).__name__}")
    items = list(value)
    if len(items) < min_len:
        raise ValueError(f"{field} needs at least {min_len} item(s), got {len(items)}")
    if len(items) > max_len:
        raise ValueError(f"{field} supports at most {max_len} item(s), got {len(items)}")
    return items


def _fit(text: str, max_chars: int) -> str:
    """Collapse whitespace and hard-truncate with an ellipsis."""
    s = " ".join(str(text).split())
    if len(s) <= max_chars:
        return s
    if max_chars <= 1:
        return s[:max_chars]
    return s[: max_chars - 1].rstrip() + "…"


def _label(value: Any, field: str, max_chars: int, *, allow_empty: bool = False) -> str:
    if value is None and allow_empty:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string, got {type(value).__name__}")
    s = " ".join(value.split())
    if not s:
        if allow_empty:
            return ""
        raise ValueError(f"{field} must not be empty")
    return _fit(s, max_chars)


def _wrap(text: str, width: int, max_lines: int) -> list[str]:
    """Wrap to at most ``max_lines`` lines of ``width`` chars, ellipsising the tail."""
    if not text:
        return []
    lines = textwrap.wrap(text, width=max(4, width)) or [""]
    if len(lines) <= max_lines:
        return lines
    kept = lines[: max_lines - 1] if max_lines > 1 else []
    tail = " ".join(lines[max_lines - 1 :])
    kept.append(_fit(tail, width))
    return kept


def _num(value: float) -> str:
    """Format a coordinate compactly; raises on non-finite geometry."""
    if not math.isfinite(value):
        raise ValueError("computed a non-finite coordinate")
    rounded = round(float(value), 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:g}"


# --------------------------------------------------------------------------
# primitive emitters — every one of these is in the renderer's draw plan
# --------------------------------------------------------------------------


def _text(
    x: float,
    y: float,
    content: str,
    *,
    size: float = 14,
    color: str = INK,
    anchor: str = "middle",
    weight: str = "normal",
    italic: bool = False,
) -> str:
    if not content:
        return ""
    style = ' font-style="italic"' if italic else ""
    bold = "" if weight == "normal" else f' font-weight="{weight}"'
    return (
        f'<text x="{_num(x)}" y="{_num(y)}" font-size="{_num(size)}" '
        f'fill="{color}" text-anchor="{anchor}"{bold}{style}>'
        f"{html.escape(content)}</text>"
    )


def _text_block(
    x: float,
    y: float,
    lines: Sequence[str],
    *,
    size: float = 14,
    color: str = INK,
    anchor: str = "middle",
    weight: str = "normal",
    leading: float | None = None,
) -> str:
    step = leading if leading is not None else size * 1.25
    return "".join(
        _text(x, y + i * step, line, size=size, color=color, anchor=anchor, weight=weight)
        for i, line in enumerate(lines)
    )


def _line(
    x1: float, y1: float, x2: float, y2: float, *, color: str = INK,
    width: float = 2, dashed: bool = False,
) -> str:
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    return (
        f'<line x1="{_num(x1)}" y1="{_num(y1)}" x2="{_num(x2)}" y2="{_num(y2)}" '
        f'stroke="{color}" stroke-width="{_num(width)}" stroke-linecap="round"{dash}/>'
    )


def _rect(
    x: float, y: float, w: float, h: float, *, stroke: str = INK, fill: str = "none",
    width: float = 2, rx: float = 0,
) -> str:
    r = f' rx="{_num(rx)}"' if rx else ""
    return (
        f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}"{r} '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{_num(width)}"/>'
    )


def _circle(cx: float, cy: float, r: float, *, stroke: str = INK, fill: str = "none",
            width: float = 2) -> str:
    return (
        f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="{_num(r)}" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="{_num(width)}"/>'
    )


def _polyline(points: Sequence[tuple[float, float]], *, color: str = INK,
              width: float = 2, dashed: bool = False) -> str:
    if len(points) < 2:
        raise ValueError("a polyline needs at least two points")
    pts = " ".join(f"{_num(px)},{_num(py)}" for px, py in points)
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    return (
        f'<polyline points="{pts}" fill="none" stroke="{color}" '
        f'stroke-width="{_num(width)}" stroke-linejoin="round" '
        f'stroke-linecap="round"{dash}/>'
    )


def _polygon(points: Sequence[tuple[float, float]], *, stroke: str = INK,
             fill: str = "none", width: float = 2) -> str:
    if len(points) < 3:
        raise ValueError("a polygon needs at least three points")
    pts = " ".join(f"{_num(px)},{_num(py)}" for px, py in points)
    return (
        f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" '
        f'stroke-width="{_num(width)}"/>'
    )


def _path(d: str, *, stroke: str = INK, fill: str = "none", width: float = 2,
          dashed: bool = False) -> str:
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    return (
        f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{_num(width)}" '
        f'stroke-linecap="round" stroke-linejoin="round"{dash}/>'
    )


def _arrow(
    x1: float, y1: float, x2: float, y2: float, *, color: str = INK,
    width: float = 2, head: float = 10, dashed: bool = False,
) -> str:
    """Line + explicit arrowhead polygon, in draw order (shaft, then head).

    Deliberately not a ``<marker>``: the renderer skips marker internals when
    building the draw plan, so a marker arrowhead appears before its line.
    """
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-6:
        raise ValueError("cannot draw a zero-length arrow")
    ux, uy = dx / length, dy / length
    head = min(head, length * 0.6)
    bx, by = x2 - ux * head, y2 - uy * head
    nx, ny = -uy, ux
    wing = head * 0.45
    shaft = _line(x1, y1, bx, by, color=color, width=width, dashed=dashed)
    tip = _polygon(
        [(x2, y2), (bx + nx * wing, by + ny * wing), (bx - nx * wing, by - ny * wing)],
        stroke=color,
        fill=color,
        width=1,
    )
    return shaft + tip


def _svg(width: float, height: float, parts: Sequence[str]) -> str:
    body = "".join(p for p in parts if p)
    out = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_num(width)} '
        f'{_num(height)}">'
        f'<rect x="0" y="0" width="{_num(width)}" height="{_num(height)}" '
        f'fill="{BACKGROUND}"/>'
        f"{body}</svg>"
    )
    if len(out) > MAX_SVG_CHARS:
        raise ValueError(
            f"rendered diagram is {len(out)} chars, over the {MAX_SVG_CHARS} limit; "
            "shorten the labels or use fewer elements"
        )
    return out


def _anchor_for(cos_t: float) -> str:
    if cos_t > 0.3:
        return "start"
    if cos_t < -0.3:
        return "end"
    return "middle"


# --------------------------------------------------------------------------
# 1. free body diagram
# --------------------------------------------------------------------------


def _normalise_force(item: Any, idx: int) -> tuple[str, float, float]:
    where = f"forces[{idx}]"
    if isinstance(item, Mapping):
        label = item.get("label")
        angle = item.get("angle", item.get("angle_deg"))
        rel = item.get("length", 1.0)
    elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
        parts = list(item)
        if len(parts) not in (2, 3):
            raise ValueError(f"{where} must be (label, angle) or (label, angle, length)")
        label, angle = parts[0], parts[1]
        rel = parts[2] if len(parts) == 3 else 1.0
    else:
        raise ValueError(
            f"{where} must be a mapping or a (label, angle) pair, "
            f"got {type(item).__name__}"
        )
    if angle is None:
        raise ValueError(f"{where} is missing an 'angle' (degrees from +x axis)")
    return (
        _label(label, f"{where}.label", 16),
        _number(angle, f"{where}.angle"),
        max(0.45, min(1.0, _number(rel, f"{where}.length"))),
    )


def free_body_diagram(body_label: str, forces: Sequence[Any]) -> str:
    """A body with labelled force arrows radiating out at the given angles.

    ``forces`` is a sequence of ``{"label": str, "angle": deg}`` mappings (or
    ``(label, angle)`` / ``(label, angle, length)`` tuples). Angles follow the
    maths convention: 0 deg points right, 90 deg points up.
    """
    body = _label(body_label, "body_label", 22)
    items = [
        _normalise_force(f, i)
        for i, f in enumerate(_sequence(forces, "forces", min_len=1, max_len=7))
    ]

    w, h = 480, 380
    cx, cy = 240, 190
    bw, bh = 88, 66
    parts: list[str] = []

    # the body first — that is what a teacher outlines before hanging forces off it
    parts.append(_rect(cx - bw / 2, cy - bh / 2, bw, bh, stroke=INK, fill=LIGHT_FILL,
                       width=2.4, rx=8))
    parts.append(
        _text_block(cx, cy + 1, _wrap(body, 11, 2), size=13, color=INK,
                    weight="bold", leading=15)
    )

    base = 96.0
    for label, angle, rel in items:
        theta = math.radians(angle)
        ux, uy = math.cos(theta), -math.sin(theta)
        # start just outside the body outline
        start_r = (bw / 2 + 6) if abs(ux) > abs(uy) * (bw / bh) else (bh / 2 + 6)
        sx, sy = cx + ux * start_r, cy + uy * start_r
        ex, ey = cx + ux * (start_r + base * rel), cy + uy * (start_r + base * rel)
        parts.append(_arrow(sx, sy, ex, ey, color=PRIMARY, width=2.4, head=11))
        lx, ly = ex + ux * 12, ey + uy * 12
        parts.append(
            _text(lx, ly + (5 if uy > 0.2 else (-3 if uy < -0.2 else 4)),
                  label, size=13.5, color=AMBER, anchor=_anchor_for(ux), weight="bold")
        )

    return _svg(w, h, parts)


# --------------------------------------------------------------------------
# 2. comparison table
# --------------------------------------------------------------------------


def comparison_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    title: str | None = None,
) -> str:
    """A ruled 2- or 3-column comparison table."""
    heads = _sequence(headers, "headers", min_len=2, max_len=3)
    ncols = len(heads)
    heads = [_label(hd, f"headers[{i}]", 22) for i, hd in enumerate(heads)]
    body_rows = _sequence(rows, "rows", min_len=1, max_len=7)

    cells: list[list[str]] = []
    for r, row in enumerate(body_rows):
        cols = _sequence(row, f"rows[{r}]", min_len=ncols, max_len=ncols)
        cells.append([_label(c, f"rows[{r}][{c_i}]", 62) for c_i, c in enumerate(cols)])

    heading = _label(title, "title", 46, allow_empty=True)

    w = 540
    margin = 24
    tw = w - 2 * margin
    cw = tw / ncols
    chars = int(cw / 6.4)
    top = 54 if heading else 22
    head_h = 40

    # two lines per cell keeps a 3x7 table comfortably under MAX_SVG_CHARS
    wrapped = [[_wrap(c, chars, 2) for c in row] for row in cells]
    row_hs = [max(36.0, 14.0 + 19.0 * max(len(c) for c in row)) for row in wrapped]
    table_h = head_h + sum(row_hs)
    h = top + table_h + 22

    parts: list[str] = []
    if heading:
        parts.append(_text(w / 2, 32, heading, size=17, color=INK, weight="bold"))

    # grid first, contents after — the way it goes up on a board
    parts.append(_rect(margin, top, tw, head_h, stroke=INK, fill=LIGHT_FILL, width=2))
    parts.append(_rect(margin, top, tw, table_h, stroke=INK, fill="none", width=2.2))
    for c in range(1, ncols):
        x = margin + c * cw
        parts.append(_line(x, top, x, top + table_h, color=INK, width=1.6))
    y = top + head_h
    for rh in row_hs[:-1]:
        parts.append(_line(margin, y, margin + tw, y, color=MUTED, width=1.4))
        y += rh
    parts.append(_line(margin, top + head_h, margin + tw, top + head_h, color=INK,
                       width=2))

    for c, hd in enumerate(heads):
        cxx = margin + c * cw + cw / 2
        lines = _wrap(hd, chars, 2)
        y0 = top + head_h / 2 + 5 - (len(lines) - 1) * 7
        parts.append(_text_block(cxx, y0, lines, size=13.5, color=PRIMARY,
                                 weight="bold", leading=15))

    y = top + head_h
    for r, row in enumerate(wrapped):
        for c, lines in enumerate(row):
            cxx = margin + c * cw + cw / 2
            y0 = y + row_hs[r] / 2 + 4.5 - (len(lines) - 1) * 8.5
            parts.append(_text_block(cxx, y0, lines, size=12.5, color=INK, leading=17))
        y += row_hs[r]

    return _svg(w, h, parts)


# --------------------------------------------------------------------------
# 3. boxed derivation
# --------------------------------------------------------------------------


def boxed_derivation(steps: Sequence[str], title: str | None = None) -> str:
    """Sequential derivation steps, with the last one boxed as the result."""
    raw = _sequence(steps, "steps", min_len=2, max_len=7)
    lines = [_label(s, f"steps[{i}]", 80) for i, s in enumerate(raw)]
    heading = _label(title, "title", 46, allow_empty=True)

    w = 500
    chars = 42
    wrapped = [_wrap(s, chars, 2) for s in lines]

    top = 50 if heading else 26
    gap = 30.0
    step_hs = [16.0 + 20.0 * len(ln) for ln in wrapped]
    h = top + sum(step_hs) + gap * (len(wrapped) - 1) + 26

    parts: list[str] = []
    if heading:
        parts.append(_text(w / 2, 30, heading, size=17, color=INK, weight="bold"))

    y = top
    last = len(wrapped) - 1
    for i, ln in enumerate(wrapped):
        block_h = step_hs[i]
        if i == last:
            bw = min(w - 60, max(200.0, max(len(t) for t in ln) * 9.6 + 44))
            # box first, then the text — a filled rect drawn after would hide it
            parts.append(
                _rect(w / 2 - bw / 2, y, bw, block_h, stroke=PRIMARY,
                      fill=LIGHT_FILL, width=2.6, rx=7)
            )
            parts.append(
                _text_block(w / 2, y + block_h / 2 + 5.5 - (len(ln) - 1) * 10, ln,
                            size=16, color=PRIMARY, weight="bold", leading=20)
            )
        else:
            parts.append(
                _text_block(w / 2, y + block_h / 2 + 5 - (len(ln) - 1) * 10, ln,
                            size=15.5, color=INK, leading=20)
            )
        y += block_h
        if i != last:
            parts.append(
                _arrow(w / 2, y + 5, w / 2, y + gap - 5, color=MUTED, width=1.8, head=8)
            )
            y += gap

    return _svg(w, h, parts)


# --------------------------------------------------------------------------
# 4. labelled axes plot
# --------------------------------------------------------------------------


def _normalise_annotation(item: Any, idx: int) -> tuple[float, float, str]:
    where = f"annotations[{idx}]"
    if isinstance(item, Mapping):
        ax, ay, txt = item.get("x"), item.get("y"), item.get("text", item.get("label"))
    elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
        parts = list(item)
        if len(parts) != 3:
            raise ValueError(f"{where} must be (x, y, text)")
        ax, ay, txt = parts
    else:
        raise ValueError(f"{where} must be a mapping or an (x, y, text) triple")
    if ax is None or ay is None:
        raise ValueError(f"{where} needs both 'x' and 'y'")
    return _number(ax, f"{where}.x"), _number(ay, f"{where}.y"), _label(txt, f"{where}.text", 26)


def labeled_axes_plot(
    x_label: str,
    y_label: str,
    curve_points: Sequence[Sequence[float]],
    annotations: Sequence[Any] | None = None,
    title: str | None = None,
) -> str:
    """A 2D plot: arrowed axes, one curve, and optional callouts on the curve.

    ``curve_points`` are ``(x, y)`` pairs in *data* coordinates; they are
    auto-scaled to the plot area.
    """
    xl = _label(x_label, "x_label", 28)
    yl = _label(y_label, "y_label", 28)
    heading = _label(title, "title", 46, allow_empty=True)
    pts_in = _sequence(curve_points, "curve_points", min_len=2, max_len=160)

    data: list[tuple[float, float]] = []
    for i, p in enumerate(pts_in):
        pair = _sequence(p, f"curve_points[{i}]", min_len=2, max_len=2)
        data.append((_number(pair[0], f"curve_points[{i}][0]"),
                     _number(pair[1], f"curve_points[{i}][1]")))

    notes = [
        _normalise_annotation(a, i)
        for i, a in enumerate(_sequence(annotations or [], "annotations",
                                        min_len=0, max_len=4))
    ]

    w, h = 540, 380
    left, right = 74.0, 494.0
    bottom, topy = 306.0, 74.0

    xs = [p[0] for p in data] + [n[0] for n in notes]
    ys = [p[1] for p in data] + [n[1] for n in notes]
    x_lo, x_hi = min(xs), max(xs)
    y_lo, y_hi = min(ys), max(ys)
    if math.isclose(x_hi, x_lo):
        x_lo, x_hi = x_lo - 1.0, x_hi + 1.0
    if math.isclose(y_hi, y_lo):
        y_lo, y_hi = y_lo - 1.0, y_hi + 1.0
    pad_y = (y_hi - y_lo) * 0.08
    y_lo, y_hi = y_lo - pad_y, y_hi + pad_y

    def sx(v: float) -> float:
        return left + (v - x_lo) / (x_hi - x_lo) * (right - left)

    def sy(v: float) -> float:
        return bottom - (v - y_lo) / (y_hi - y_lo) * (bottom - topy)

    parts: list[str] = []
    if heading:
        parts.append(_text(w / 2, 34, heading, size=17, color=INK, weight="bold"))

    parts.append(_arrow(left - 14, bottom, right + 26, bottom, color=INK, width=2.2))
    parts.append(_arrow(left, bottom + 14, left, topy - 26, color=INK, width=2.2))
    parts.append(_text(right + 22, bottom + 26, _fit(xl, 28), size=13.5, color=MUTED,
                       anchor="end", italic=True))
    # sits under the title band, not across it
    parts.append(_text(left + 10, topy - 14, _fit(yl, 24), size=13.5, color=MUTED,
                       anchor="start", italic=True))

    parts.append(_polyline([(sx(px), sy(py)) for px, py in data], color=PRIMARY,
                           width=2.8))

    for ax, ay, txt in notes:
        px, py = sx(ax), sy(ay)
        above = py > topy + 46
        ty = py - 20 if above else py + 30
        parts.append(_circle(px, py, 5, stroke=AMBER, fill="none", width=2.2))
        parts.append(_line(px, py + (-8 if above else 8), px, ty + (7 if above else -13),
                           color=AMBER, width=1.4, dashed=True))
        anchor = "middle"
        if px < left + 60:
            anchor = "start"
        elif px > right - 60:
            anchor = "end"
        parts.append(_text(px, ty, txt, size=12.5, color=AMBER, anchor=anchor,
                           weight="bold"))

    return _svg(w, h, parts)


# --------------------------------------------------------------------------
# 5. ray diagram
# --------------------------------------------------------------------------

_OPTIC_TYPES = ("convex_lens", "concave_lens", "concave_mirror", "convex_mirror")


def _clip_ray(
    x0: float, y0: float, dx: float, dy: float,
    xmin: float, xmax: float, ymin: float, ymax: float,
) -> tuple[float, float]:
    """Endpoint of the ray from (x0, y0) along (dx, dy), clipped to the box.

    Extending a ray only in x lets steep rays shoot far below the viewBox; the
    renderer forces ``overflow="visible"`` so they would be drawn outside the
    diagram frame instead of being cropped.
    """
    t = math.inf
    for d, p, lo, hi in ((dx, x0, xmin, xmax), (dy, y0, ymin, ymax)):
        if abs(d) < 1e-9:
            continue
        t = min(t, ((hi if d > 0 else lo) - p) / d)
    if not math.isfinite(t) or t <= 0:
        raise ValueError("ray leaves the drawing area immediately")
    return x0 + dx * t, y0 + dy * t


def ray_diagram(optic_type: str, object_pos: float, focal_length: float) -> str:
    """Principal-ray construction for a thin lens or spherical mirror.

    ``object_pos`` and ``focal_length`` are positive magnitudes in the same
    (arbitrary) units — cm is the usual choice. The drawing is auto-scaled.
    Virtual rays and virtual images are dashed.
    """
    if not isinstance(optic_type, str):
        raise ValueError("optic_type must be a string")
    kind = optic_type.strip().lower()
    if kind not in _OPTIC_TYPES:
        raise ValueError(
            f"optic_type must be one of {', '.join(_OPTIC_TYPES)}, got {optic_type!r}"
        )
    d_o = _number(object_pos, "object_pos")
    f = _number(focal_length, "focal_length")
    if d_o <= 0:
        raise ValueError("object_pos must be positive (distance in front of the optic)")
    if f <= 0:
        raise ValueError(
            "focal_length must be a positive magnitude; the sign is implied by optic_type"
        )

    converging = kind in ("convex_lens", "concave_mirror")
    if converging and abs(d_o - f) < 0.25 * f:
        raise ValueError(
            "object_pos is too close to focal_length; the image runs off to infinity. "
            "Keep |object_pos - focal_length| >= 0.25 * focal_length."
        )

    is_lens = kind.endswith("lens")
    if is_lens:
        f_s = f if kind == "convex_lens" else -f
        v = 1.0 / (1.0 / f_s - 1.0 / d_o)  # cartesian: +v is right of the lens
        real = v > 0
        m = -v / d_o
        img_side = 1.0  # +1 => image plotted to the right of the optic
    else:
        f_s = f if kind == "concave_mirror" else -f
        v = 1.0 / (1.0 / f_s - 1.0 / d_o)  # real-is-positive: +v is in front (left)
        real = v > 0
        m = -v / d_o
        img_side = -1.0

    w, h = 580, 360
    cx, cy = 290.0, 186.0
    span = max(d_o, abs(v), 2.0 * f)
    s = 196.0 / span

    h_o = 62.0
    h_i = m * h_o
    if abs(h_i) > 104:
        shrink = 104 / abs(h_i)
        h_o *= shrink
        h_i *= shrink

    x_obj = cx - d_o * s
    y_obj_tip = cy - h_o
    x_img = cx + img_side * v * s
    y_img_tip = cy - h_i
    left_edge, right_edge = 34.0, w - 34.0
    half = 96.0

    parts: list[str] = []

    # principal axis, then the optic, then the object — teacher order
    parts.append(_line(left_edge, cy, right_edge, cy, color=MUTED, width=1.6))

    if kind == "convex_lens":
        parts.append(_path(
            f"M {_num(cx)} {_num(cy - half)} Q {_num(cx + 26)} {_num(cy)} "
            f"{_num(cx)} {_num(cy + half)} Q {_num(cx - 26)} {_num(cy)} "
            f"{_num(cx)} {_num(cy - half)} Z",
            stroke=PRIMARY, fill=LIGHT_FILL, width=2.4))
    elif kind == "concave_lens":
        parts.append(_path(
            f"M {_num(cx - 15)} {_num(cy - half)} Q {_num(cx + 9)} {_num(cy)} "
            f"{_num(cx - 15)} {_num(cy + half)} L {_num(cx + 15)} {_num(cy + half)} "
            f"Q {_num(cx - 9)} {_num(cy)} {_num(cx + 15)} {_num(cy - half)} Z",
            stroke=PRIMARY, fill=LIGHT_FILL, width=2.4))
    elif kind == "concave_mirror":
        parts.append(_path(
            f"M {_num(cx - 16)} {_num(cy - half)} Q {_num(cx + 22)} {_num(cy)} "
            f"{_num(cx - 16)} {_num(cy + half)}", stroke=PRIMARY, fill="none", width=3))
        for i in range(5):
            yy = cy - half + 8 + i * (2 * half - 16) / 4
            off = 22 * (1 - ((yy - cy) / half) ** 2)
            parts.append(_line(cx - 16 + off, yy, cx - 6 + off, yy - 9, color=MUTED,
                               width=1.4))
    else:  # convex_mirror
        parts.append(_path(
            f"M {_num(cx + 16)} {_num(cy - half)} Q {_num(cx - 22)} {_num(cy)} "
            f"{_num(cx + 16)} {_num(cy + half)}", stroke=PRIMARY, fill="none", width=3))
        for i in range(5):
            yy = cy - half + 8 + i * (2 * half - 16) / 4
            off = 22 * (1 - ((yy - cy) / half) ** 2)
            parts.append(_line(cx + 16 - off, yy, cx + 26 - off, yy - 9, color=MUTED,
                               width=1.4))

    # Focal points. A lens has one on each side; a mirror has exactly one —
    # in front for a concave mirror, virtual and behind for a convex one.
    if is_lens:
        f_signs: tuple[int, ...] = (-1, 1)
    elif kind == "concave_mirror":
        f_signs = (-1,)
    else:
        f_signs = (1,)
    for sign in f_signs:
        fx = cx + sign * f * s
        if left_edge + 6 < fx < right_edge - 6:
            parts.append(_line(fx, cy - 6, fx, cy + 6, color=MUTED, width=1.6))
            parts.append(_text(fx, cy + 21, "F", size=12.5, color=MUTED, weight="bold"))

    # object
    parts.append(_arrow(x_obj, cy, x_obj, y_obj_tip, color=GREEN, width=2.6, head=11))
    parts.append(_text(x_obj, cy + 22, "object", size=12.5, color=GREEN, anchor="middle"))

    # --- principal rays -------------------------------------------------
    optic_x = cx
    box = (left_edge + 4, right_edge - 4, 26.0, h - 34.0)

    def outgoing(from_x: float, from_y: float) -> list[str]:
        """Ray leaving ``(from_x, from_y)`` consistent with the image point."""
        seg: list[str] = []
        if real:
            seg.append(_line(from_x, from_y, x_img, y_img_tip, color=RED, width=2))
        else:
            # The real ray carries on away from the virtual image; only its
            # backward extension reaches the image, so that part is dashed.
            ex, ey = _clip_ray(from_x, from_y, from_x - x_img, from_y - y_img_tip, *box)
            seg.append(_line(from_x, from_y, ex, ey, color=RED, width=2))
            seg.append(_line(from_x, from_y, x_img, y_img_tip, color=RED, width=1.6,
                             dashed=True))
        return seg

    # ray 1: parallel to the axis, then through / away from the focus
    parts.append(_line(x_obj, y_obj_tip, optic_x, y_obj_tip, color=RED, width=2))
    parts.extend(outgoing(optic_x, y_obj_tip))
    # ray 2: through the optical centre / striking the pole
    parts.append(_line(x_obj, y_obj_tip, optic_x, cy, color=RED, width=2))
    parts.extend(outgoing(optic_x, cy))

    # image
    parts.append(_arrow(x_img, cy, x_img, y_img_tip, color=AMBER, width=2.6, head=11,
                        dashed=not real))
    parts.append(_text(x_img, cy + (22 if h_i > 0 else -12), "image", size=12.5,
                       color=AMBER, anchor="middle"))

    caption = "{} — {}, {}".format(
        kind.replace("_", " "),
        "real" if real else "virtual",
        "inverted" if m < 0 else "erect",
    )
    parts.append(_text(w / 2, h - 14, caption, size=13, color=INK, weight="bold"))

    return _svg(w, h, parts)


# --------------------------------------------------------------------------
# 6. circuit diagram
# --------------------------------------------------------------------------

_COMPONENT_TYPES = (
    "battery", "cell", "resistor", "capacitor", "inductor", "bulb",
    "switch", "ammeter", "voltmeter",
)


def _normalise_component(item: Any, idx: int) -> tuple[str, str]:
    where = f"components[{idx}]"
    if isinstance(item, Mapping):
        ctype, label = item.get("type"), item.get("label", "")
    elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
        parts = list(item)
        if len(parts) not in (1, 2):
            raise ValueError(f"{where} must be (type,) or (type, label)")
        ctype = parts[0]
        label = parts[1] if len(parts) == 2 else ""
    elif isinstance(item, str):
        ctype, label = item, ""
    else:
        raise ValueError(f"{where} must be a mapping, a tuple or a type string")
    if not isinstance(ctype, str):
        raise ValueError(f"{where}.type must be a string")
    t = ctype.strip().lower()
    if t not in _COMPONENT_TYPES:
        raise ValueError(
            f"{where}.type must be one of {', '.join(_COMPONENT_TYPES)}, got {ctype!r}"
        )
    return t, _label(label, f"{where}.label", 14, allow_empty=True)


def _symbol(t: str, cx: float, cy: float, horizontal: bool) -> tuple[str, float]:
    """Return (markup, half-extent along the wire) for one component symbol."""
    def pt(along: float, across: float) -> tuple[float, float]:
        return (cx + along, cy + across) if horizontal else (cx - across, cy + along)

    out: list[str] = []
    if t == "resistor":
        half = 26.0
        pts = [pt(-half, 0)]
        zig = [(-20, -9), (-12, 9), (-4, -9), (4, 9), (12, -9), (20, 9)]
        pts += [pt(a, b) for a, b in zig]
        pts.append(pt(half, 0))
        out.append(_polyline(pts, color=INK, width=2.2))
    elif t in ("battery", "cell"):
        half = 22.0
        out.append(_line(*pt(-half, 0), *pt(-8, 0), color=INK, width=2.2))
        out.append(_line(*pt(-8, -14), *pt(-8, 14), color=INK, width=2.6))
        out.append(_line(*pt(-1, -7), *pt(-1, 7), color=INK, width=2.6))
        if t == "battery":
            out.append(_line(*pt(6, -14), *pt(6, 14), color=INK, width=2.6))
            out.append(_line(*pt(13, -7), *pt(13, 7), color=INK, width=2.6))
            out.append(_line(*pt(13, 0), *pt(half, 0), color=INK, width=2.2))
        else:
            out.append(_line(*pt(-1, 0), *pt(half, 0), color=INK, width=2.2))
    elif t == "capacitor":
        half = 18.0
        out.append(_line(*pt(-half, 0), *pt(-5, 0), color=INK, width=2.2))
        out.append(_line(*pt(-5, -14), *pt(-5, 14), color=INK, width=2.6))
        out.append(_line(*pt(5, -14), *pt(5, 14), color=INK, width=2.6))
        out.append(_line(*pt(5, 0), *pt(half, 0), color=INK, width=2.2))
    elif t == "inductor":
        half = 26.0
        arcs = []
        for i in range(4):
            a0 = -20 + i * 10
            p0, p1 = pt(a0, 0), pt(a0 + 10, 0)
            sweep = 1 if horizontal else 0
            arcs.append(
                f"M {_num(p0[0])} {_num(p0[1])} A 5 5 0 0 {sweep} "
                f"{_num(p1[0])} {_num(p1[1])}"
            )
        out.append(_line(*pt(-half, 0), *pt(-20, 0), color=INK, width=2.2))
        out.append(_path(" ".join(arcs), stroke=INK, fill="none", width=2.2))
        out.append(_line(*pt(20, 0), *pt(half, 0), color=INK, width=2.2))
    elif t == "bulb":
        half = 22.0
        out.append(_line(*pt(-half, 0), *pt(-14, 0), color=INK, width=2.2))
        out.append(_circle(cx, cy, 14, stroke=AMBER, fill="none", width=2.4))
        out.append(_line(*pt(-10, -10), *pt(10, 10), color=AMBER, width=1.8))
        out.append(_line(*pt(-10, 10), *pt(10, -10), color=AMBER, width=1.8))
        out.append(_line(*pt(14, 0), *pt(half, 0), color=INK, width=2.2))
    elif t == "switch":
        half = 22.0
        out.append(_line(*pt(-half, 0), *pt(-12, 0), color=INK, width=2.2))
        out.append(_circle(*pt(-12, 0), 3, stroke=INK, fill=INK, width=1))
        out.append(_line(*pt(-12, 0), *pt(10, -13), color=INK, width=2.4))
        out.append(_circle(*pt(12, 0), 3, stroke=INK, fill=INK, width=1))
        out.append(_line(*pt(12, 0), *pt(half, 0), color=INK, width=2.2))
    else:  # ammeter / voltmeter
        half = 20.0
        out.append(_line(*pt(-half, 0), *pt(-13, 0), color=INK, width=2.2))
        out.append(_circle(cx, cy, 13, stroke=PRIMARY, fill="none", width=2.4))
        out.append(_text(cx, cy + 5, "A" if t == "ammeter" else "V", size=14,
                         color=PRIMARY, weight="bold"))
        out.append(_line(*pt(13, 0), *pt(half, 0), color=INK, width=2.2))
    return "".join(out), half


def circuit_diagram(components: Sequence[Any]) -> str:
    """A single series loop with labelled components spaced around it.

    ``components`` entries are ``{"type": ..., "label": ...}`` mappings,
    ``(type, label)`` tuples, or bare type strings. Supported types:
    battery, cell, resistor, capacitor, inductor, bulb, switch, ammeter,
    voltmeter.
    """
    items = [
        _normalise_component(c, i)
        for i, c in enumerate(_sequence(components, "components", min_len=2, max_len=6))
    ]

    w, h = 520, 366
    x0, x1 = 82.0, 438.0
    y0, y1 = 74.0, 268.0
    side_w, side_h = x1 - x0, y1 - y0
    perim = 2 * (side_w + side_h)
    # corner distances, clockwise from the top-left
    bounds = [0.0, side_w, side_w + side_h, 2 * side_w + side_h, perim]

    def locate(t: float) -> tuple[float, float, bool]:
        """Perimeter distance -> (x, y, is_horizontal)."""
        if t <= bounds[1]:
            return x0 + t, y0, True
        if t <= bounds[2]:
            return x1, y0 + (t - bounds[1]), False
        if t <= bounds[3]:
            return x1 - (t - bounds[2]), y1, True
        return x0, y1 - (t - bounds[3]), False

    n = len(items)
    slots: list[float] = []
    for i in range(n):
        t = (i + 0.5) * perim / n
        seg = next(k for k in range(4) if t <= bounds[k + 1])
        lo, hi = bounds[seg], bounds[seg + 1]
        t = min(max(t, lo + 34), hi - 34)
        slots.append(t)

    parts: list[str] = []

    # wires first: the loop is what gets sketched before anything sits on it
    cuts: list[tuple[float, float]] = []
    for t, (ctype, _lbl) in zip(slots, items):
        px, py, horiz = locate(t)
        _markup, half = _symbol(ctype, px, py, horiz)
        cuts.append((t - half, t + half))

    edges = [0.0]
    for lo, hi in cuts:
        edges.extend((lo, hi))
    edges.append(perim)
    for k in range(0, len(edges) - 1, 2):
        a, b = edges[k], edges[k + 1]
        if b - a < 0.5:
            continue
        # walk the gap corner by corner so wires follow the rectangle
        stops = [a] + [c for c in bounds[1:4] if a < c < b] + [b]
        pts = [locate(min(sv, perim - 1e-6))[:2] for sv in stops]
        parts.append(_polyline(pts, color=INK, width=2.2))

    for t, (ctype, label) in zip(slots, items):
        px, py, horiz = locate(t)
        markup, _half = _symbol(ctype, px, py, horiz)
        parts.append(markup)
        if not label:
            continue
        if horiz:
            above = py < (y0 + y1) / 2
            parts.append(_text(px, py - 26 if above else py + 36, label, size=13,
                               color=AMBER, weight="bold"))
        else:
            leftish = px < (x0 + x1) / 2
            parts.append(_text(px + (-30 if leftish else 30), py + 5, label, size=13,
                               color=AMBER, weight="bold",
                               anchor="end" if leftish else "start"))

    # sits clear of the bottom-row component labels at y1 + 36
    parts.append(_text(w / 2, h - 12, "series circuit", size=13, color=MUTED))
    return _svg(w, h, parts)


# --------------------------------------------------------------------------
# 7. vector resolution
# --------------------------------------------------------------------------


def vector_resolution(
    magnitude_label: str,
    angle_deg: float,
    x_label: str,
    y_label: str,
) -> str:
    """A vector with dashed x/y components and the angle arc marked."""
    mag = _label(magnitude_label, "magnitude_label", 18)
    xl = _label(x_label, "x_label", 18)
    yl = _label(y_label, "y_label", 18)
    angle = _number(angle_deg, "angle_deg")
    if not -720 <= angle <= 720:
        raise ValueError("angle_deg must lie between -720 and 720")
    theta = math.radians(angle) % (2 * math.pi)
    deg = math.degrees(theta)
    if abs(math.sin(theta)) < 1e-3 or abs(math.cos(theta)) < 1e-3:
        raise ValueError(
            "angle_deg must not be a multiple of 90 deg; there is nothing to resolve"
        )

    w, h = 480, 380
    ox, oy = 240.0, 200.0
    length = 138.0
    vx, vy = length * math.cos(theta), length * math.sin(theta)
    tipx, tipy = ox + vx, oy - vy

    parts: list[str] = []
    # axes first
    parts.append(_arrow(50, oy, w - 34, oy, color=MUTED, width=1.8, head=9))
    parts.append(_arrow(ox, h - 66, ox, 34, color=MUTED, width=1.8, head=9))
    parts.append(_text(w - 30, oy + 20, "x", size=13, color=MUTED, anchor="end",
                       italic=True))
    parts.append(_text(ox + 14, 38, "y", size=13, color=MUTED, anchor="start",
                       italic=True))

    # the vector itself
    parts.append(_arrow(ox, oy, tipx, tipy, color=PRIMARY, width=3, head=13))

    # components
    parts.append(_arrow(ox, oy, ox + vx, oy, color=GREEN, width=2.2, head=10,
                        dashed=True))
    parts.append(_arrow(ox, oy, ox, oy - vy, color=GREEN, width=2.2, head=10,
                        dashed=True))
    # projection guides closing the rectangle
    parts.append(_line(ox + vx, oy, tipx, tipy, color=MUTED, width=1.4, dashed=True))
    parts.append(_line(ox, oy - vy, tipx, tipy, color=MUTED, width=1.4, dashed=True))

    # angle arc, swept anticlockwise on screen from the +x axis
    r = 46.0
    large = 1 if deg > 180 else 0
    parts.append(_path(
        f"M {_num(ox + r)} {_num(oy)} A {_num(r)} {_num(r)} 0 {large} 0 "
        f"{_num(ox + r * math.cos(theta))} {_num(oy - r * math.sin(theta))}",
        stroke=AMBER, fill="none", width=2))

    half = theta / 2
    parts.append(_text(ox + (r + 20) * math.cos(half), oy - (r + 20) * math.sin(half) + 5,
                       f"{deg:g}°", size=13.5, color=AMBER, weight="bold"))

    # labels
    parts.append(_text(tipx + 14 * math.cos(theta), tipy - 14 * math.sin(theta) + 5,
                       mag, size=15, color=PRIMARY, weight="bold",
                       anchor=_anchor_for(math.cos(theta))))
    parts.append(_text(ox + vx / 2, oy + (22 if math.sin(theta) > 0 else -14), xl,
                       size=13, color=GREEN, weight="bold"))
    parts.append(_text(ox + (-12 if math.cos(theta) > 0 else 12), oy - vy / 2 + 5, yl,
                       size=13, color=GREEN, weight="bold",
                       anchor="end" if math.cos(theta) > 0 else "start"))
    return _svg(w, h, parts)


# --------------------------------------------------------------------------
# 8. process flow
# --------------------------------------------------------------------------


def process_flow(stages: Sequence[str], title: str | None = None) -> str:
    """Labelled boxes joined by arrows; wraps onto snaking rows past three."""
    raw = _sequence(stages, "stages", min_len=2, max_len=8)
    labels = [_label(s, f"stages[{i}]", 60) for i, s in enumerate(raw)]
    heading = _label(title, "title", 46, allow_empty=True)

    n = len(labels)
    cols = min(n, 3)
    rows = math.ceil(n / cols)
    bw, bh = 138.0, 74.0
    gx, gy = 54.0, 60.0
    margin = 26.0

    w = 2 * margin + cols * bw + (cols - 1) * gx
    top = 54.0 if heading else 26.0
    h = top + rows * bh + (rows - 1) * gy + 26

    def box_xy(idx: int) -> tuple[float, float]:
        r = idx // cols
        c_in = idx % cols
        c = c_in if r % 2 == 0 else (cols - 1 - c_in)
        return margin + c * (bw + gx), top + r * (bh + gy)

    parts: list[str] = []
    if heading:
        parts.append(_text(w / 2, 32, heading, size=17, color=INK, weight="bold"))

    for i, label in enumerate(labels):
        bx, by = box_xy(i)
        fill = LIGHT_FILL if i in (0, n - 1) else PALE_FILL
        stroke = PRIMARY if i in (0, n - 1) else INK
        parts.append(_rect(bx, by, bw, bh, stroke=stroke, fill=fill, width=2.2, rx=8))
        lines = _wrap(label, 17, 3)
        y0 = by + bh / 2 + 5 - (len(lines) - 1) * 8
        parts.append(_text_block(bx + bw / 2, y0, lines, size=12.5, color=INK,
                                 weight="bold", leading=16))
        if i == n - 1:
            continue
        nx, ny = box_xy(i + 1)
        if ny == by:  # same row
            if nx > bx:
                parts.append(_arrow(bx + bw + 6, by + bh / 2, nx - 6, ny + bh / 2,
                                    color=AMBER, width=2.2, head=11))
            else:
                parts.append(_arrow(bx - 6, by + bh / 2, nx + bw + 6, ny + bh / 2,
                                    color=AMBER, width=2.2, head=11))
        else:  # drop to the next row, directly below
            parts.append(_arrow(bx + bw / 2, by + bh + 6, nx + bw / 2, ny - 6,
                                color=AMBER, width=2.2, head=11))

    return _svg(w, h, parts)


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

TEMPLATES: dict[str, Callable[..., str]] = {
    "free_body_diagram": free_body_diagram,
    "comparison_table": comparison_table,
    "boxed_derivation": boxed_derivation,
    "labeled_axes_plot": labeled_axes_plot,
    "ray_diagram": ray_diagram,
    "circuit_diagram": circuit_diagram,
    "vector_resolution": vector_resolution,
    "process_flow": process_flow,
}


def render(name: str, **kwargs: Any) -> str:
    """Render ``name`` from :data:`TEMPLATES`.

    Raises ``ValueError`` for an unknown template or an argument mismatch, so
    callers never have to distinguish between "bad name" and "bad payload".
    """
    if not isinstance(name, str):
        raise ValueError(f"template name must be a string, got {type(name).__name__}")
    fn = TEMPLATES.get(name)
    if fn is None:
        raise ValueError(
            f"unknown diagram template {name!r}; available: "
            f"{', '.join(sorted(TEMPLATES))}"
        )
    try:
        return fn(**kwargs)
    except TypeError as exc:  # wrong/missing keyword arguments
        raise ValueError(f"bad arguments for template {name!r}: {exc}") from exc
