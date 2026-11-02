"""Views of the unbounded plane and the exact arithmetic that moves them
(spec/hashlife.md "View and render").

A view is three integers. ``mag`` is the magnification exponent: ``mag ≥ 0`` draws each
cell as a 2^mag × 2^mag square of pixels (up to ``MAX_MAG``, 1:32); ``mag < 0`` draws each
aligned 2^−mag × 2^−mag block of cells as one pixel, so a frame costs the same at any
scale. ``(x, y)`` is the frame's top-left pixel in the *pixel plane* of that magnification,
in tree coordinates (cell y − 1): at ``mag ≥ 0`` pixel-plane point P covers tree cell
⌊P / 2^mag⌋; at ``mag < 0`` it is the aligned block whose tree origin is P · 2^−mag.
Everything here is integer arithmetic, so every port moves views identically.
"""

from __future__ import annotations

import dataclasses

MAX_MAG = 5  # 32 pixels per cell, the deepest zoom


@dataclasses.dataclass(frozen=True)
class LifeView:
    """Where a frame looks: its top-left pixel (x, y) in the pixel plane of ``mag``."""

    x: int
    y: int
    mag: int

    def __post_init__(self) -> None:
        if self.mag > MAX_MAG:
            raise ValueError(f"mag {self.mag} is past the deepest zoom ({MAX_MAG}: 32 px per cell)")


def pan(view: LifeView, dx: int, dy: int) -> LifeView:
    """Drag the picture by (dx, dy) pixels: what was under pixel (i, j) is now under
    (i + dx, j + dy)."""
    return LifeView(view.x - dx, view.y - dy, view.mag)


def zoom_at(view: LifeView, i: int, j: int, steps: int) -> LifeView:
    """Zoom by 2^steps (steps > 0 in, < 0 out), one doubling at a time, keeping pixel (i, j)
    over the same point: in, the pixel plane doubles (x' = 2(x + i) − i); out, it halves,
    flooring (x' = ⌊(x + i) / 2⌋ − i). Zooming in stops at ``MAX_MAG``."""
    x, y, mag = view.x, view.y, view.mag
    for _ in range(abs(steps)):
        if steps > 0:
            if mag == MAX_MAG:
                break
            x, y, mag = 2 * (x + i) - i, 2 * (y + j) - j, mag + 1
        else:
            x, y, mag = (x + i) // 2 - i, (y + j) // 2 - j, mag - 1
    return LifeView(x, y, mag)


def cell_at(view: LifeView, i: int, j: int) -> tuple[int, int]:
    """The cell under pixel (i, j); zoomed out, the top-left cell of the pixel's block."""
    px, py = view.x + i, view.y + j
    if view.mag >= 0:
        return px >> view.mag, (py >> view.mag) + 1
    s = -view.mag
    return px << s, (py << s) + 1


def centered(x: int, y: int, mag: int, size: tuple[int, int]) -> LifeView:
    """The view of ``size`` (width, height) pixels whose center pixel (width // 2,
    height // 2) shows cell (x, y) — or, zoomed out, the block holding it."""
    width, height = size
    if mag >= 0:
        return LifeView((x << mag) - width // 2, ((y - 1) << mag) - height // 2, mag)
    s = -mag
    return LifeView((x >> s) - width // 2, ((y - 1) >> s) - height // 2, mag)


def center_cell(view: LifeView, size: tuple[int, int]) -> tuple[int, int]:
    """The cell under the frame's center pixel (the readout a viewer shows)."""
    width, height = size
    return cell_at(view, width // 2, height // 2)


def fit(box: tuple[int, int, int, int] | None, size: tuple[int, int]) -> LifeView:
    """The deepest view (mag ≤ ``MAX_MAG``) whose frame holds the inclusive box, centered
    on it; an empty universe (``None``) gives the origin at 1:1. Raises ValueError when no
    view can hold the box (spec/hashlife.md "View and render")."""
    width, height = size
    if box is None:
        return centered(0, 0, 0, size)
    x0, y0, x1, y1 = box
    ty0, ty1 = y0 - 1, y1 - 1
    # From −mag = bits + 1 on every span is fixed (a negative v counts as −v − 1 = ~v), so
    # a box that doesn't fit there never will: a frame 0 pixels across, or 1 across while
    # the box straddles tree position 0, which no aligned block does.
    bits = max((v if v >= 0 else ~v).bit_length() for v in (x0, x1, ty0, ty1))
    mag = MAX_MAG
    while True:
        if mag >= 0:
            left, right = x0 << mag, ((x1 + 1) << mag) - 1
            top, bottom = ty0 << mag, ((ty1 + 1) << mag) - 1
        else:
            s = -mag
            left, right, top, bottom = x0 >> s, x1 >> s, ty0 >> s, ty1 >> s
        if right - left < width and bottom - top < height:
            return LifeView(
                (left + right) // 2 - width // 2, (top + bottom) // 2 - height // 2, mag
            )
        if -mag > bits + 1:
            raise ValueError(f"no view of {width} × {height} pixels holds the box {box}")
        mag -= 1
